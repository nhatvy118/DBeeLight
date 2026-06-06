"""Intent Service — classifies user queries into workflow + agent selection.

Single LLM call returns everything needed for orchestration.
Uses workflow_registry to provide structured descriptions for selection.
Falls back to general-purpose agent if no workflow matches.
"""

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional, Sequence

from openai import OpenAI
from pydantic import BaseModel

from mcp_agent.orchestration.workflow_registry import (
    get_workflow_descriptions,
    get_workflow_ids,
    get_workflow_by_id,
)

logger = logging.getLogger(__name__)

_VALID_FALLBACK_AGENTS = frozenset({"database", "excel", "chart"})

# Six orchestrator branches at the same level: three DB LangGraphs + three agents.
OrchestratorRoute = Literal[
    "db_readonly",
    "db_create_table",
    "db_mutation",
    "db_general",
    "excel",
    "chart",
]

ORCHESTRATOR_ROUTES: List[Dict[str, str]] = [
    {"id": "db_readonly", "kind": "workflow", "label": "Database read-only (SELECT, schema, list/describe tables, …)"},
    {"id": "db_create_table", "kind": "workflow", "label": "Database create table"},
    {"id": "db_mutation", "kind": "workflow", "label": "Database mutation (INSERT/UPDATE/DELETE/ALTER/DROP/…)"},
    {"id": "db_general", "kind": "agent", "label": "Database agent (general tool loop)"},
    {"id": "excel", "kind": "agent", "label": "Excel agent"},
    {"id": "chart", "kind": "agent", "label": "Chart agent (Vega-Lite visualization from SQL)"},
]

_VALID_ORCHESTRATOR_ROUTES = frozenset(r["id"] for r in ORCHESTRATOR_ROUTES)
INTENT_CONTEXT_TURNS = max(2, int(os.getenv("INTENT_CONTEXT_TURNS", "6")))
_CONNECT_DISCONNECT_UI_REPLY = (
    "To connect or disconnect a database, please use the **Connect Database** button in the side panel. "
    "Database connections are managed through the UI, not via chat."
)


AccessLevel = Literal["view_only", "read_data", "edit_data"]

# Minimum permission a caller needs to run a query of this route. Derived
# from the route deterministically — no LLM involved. Used by callers like
# share-permission gating to decide whether to allow the request.
ROUTE_ACCESS_LEVEL: Dict[str, AccessLevel] = {
    "db_readonly":     "read_data",
    "db_create_table": "edit_data",
    "db_mutation":     "edit_data",
    # General DB tool loop — could be either read or write. Mark as
    # ``read_data`` so the request is not blocked outright; SQL-level gates
    # in execute_sql() still reject mutation SQL the agent might emit.
    "db_general":      "read_data",
    # Excel and chart agents produce derived artifacts (files, Vega-Lite specs)
    # that don't mutate the project database — they only read. Sit at read_data.
    "excel":           "read_data",
    "chart":           "read_data",
}

_INTENT_CLASSIFICATION_PROMPT = """You are an orchestration router. Pick exactly ONE branch for the user request.

**Decision order (important):**
- For anything database-related, decide in this order: first try **1 → 2 → 3** (the three structured DB workflows). Only if the request clearly fits NONE of them, use **4** (general Database Agent).
- Non-database topics: use **5** or **6** when appropriate.
- If the user message includes **[UPLOADED SPREADSHEET SCHEMA]** (uploaded tabular data in SQLite; `.xlsx`/`.xls` are stored on disk for Excel tools and imported to SQL when possible):
  - **db_readonly** for count/filter/aggregate/avg/sum/min/max/distinct/join/compare/rank/lookup/SQL-style questions (keywords EN: count, filter, average, sum, how many, group by; VI: đếm, lọc, trung bình, tổng, bao nhiêu, nhóm theo).
  - **excel** when the user wants workbook **formatting** (e.g. tô màu, đổi màu nền, bold, conditional formatting), in-cell **formulas**, chart **inside the Excel file**, or structural edits to the .xlsx. If **[UPLOADED_EXCEL_PATH_*]** or **[SESSION_FILE_ID_*]** is also present, the file is already uploaded — set needs_clarification=false and route **excel**; do NOT ask the user to upload again.
  - **chart** when they ask for a **chart/plot/graph/biểu đồ/đồ thị** on data in the **connected database** (Vega-Lite), not mere table stats.
  - Do **not** pick **excel** for numeric Q&A that SQL can answer on imported tables.
- Set "semantic_retrieval" to false whenever **[UPLOADED SPREADSHEET SCHEMA]** is present. Set it to true only for unstructured document Q&A (policy/contract wording, "what does this PDF say") without tabular SQL.
- If the user asks off-topic smalltalk/personal chat that is not related to this app's capabilities, set "needs_clarification" to true and set "clarification_question" exactly to: "Please ask questions related to the database."
- If the user asks to **connect** or **disconnect** a database (action request, not just status/info), set "needs_clarification" to true and set "clarification_question" exactly to: "{connect_disconnect_reply}"

Branches:

1) "db_readonly" — Read-only SQL/data: SELECT, list/describe tables, schema exploration, aggregates without modifying data. **Do NOT** use for connect/disconnect actions or "connection info" questions.
2) "db_create_table" — CREATE TABLE / define new table structure.
3) "db_mutation" — **Only** writes / schema changes: INSERT, UPDATE, DELETE, ALTER TABLE, DROP, TRUNCATE, MERGE that modifies data. **Never** use this route for "export/download/save table to Excel or CSV" — that only **reads** data; use **db_general** (general DB agent with export tools) or **db_readonly** instead.
4) "db_general" — DB requests that need the **general tool loop**: get_connection_info / "info about the connection" (status only, not connect/disconnect actions), export table/query to Excel/CSV (`export_table_to_excel`), troubleshooting, or anything that does not fit 1–3 cleanly. **Prefer this** when the user asks to export or download a dataset as a file.
5) "excel" — Spreadsheets, CSV/XLSX, rows/columns, analyze/transform Excel files.
6) "chart" — Visualizing data from the project DB as interactive Vega-Lite charts (line/bar/pie/scatter/heatmap/histogram/area/boxplot). Pick this when the user asks for a chart, plot, graph, biểu đồ, đồ thị on data that lives in the connected database.

Reference (registry workflows for wording only):
{workflow_descriptions}

Return strict JSON with:
- "needs_clarification": REQUIRED boolean — true if ambiguous OR if user wants to connect/disconnect via chat (use UI message above). For connect/disconnect action requests, do not pick a route.
- "clarification_question": REQUIRED string or null — if needs_clarification is true, ask ONE concise follow-up question to disambiguate; otherwise null.
- "route": REQUIRED when needs_clarification=false — exactly one of: "db_readonly" | "db_create_table" | "db_mutation" | "db_general" | "excel" | "chart"
- "nl_query": normalized natural-language query
- "chart_type": chart hint if visualization requested, else null
- "table_hint": table/entity hint if mentioned, else null
- "file_format": desired OUTPUT file format explicitly requested by the user (e.g. "save as csv", "export to xlsx"). Do NOT set this from the format of an uploaded/input file — only set when the user explicitly asks for output in a specific format.
- "semantic_retrieval": true only when semantic document grounding is needed; false for SQL/filter/aggregate/ranking over structured uploaded tables

Return JSON only."""


class IntentResult(BaseModel):
    """Result of intent classification."""

    # Canonical choice among the six orchestrator branches (same level).
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    route: Optional[OrchestratorRoute] = None
    workflow_id: Optional[str] = None
    fallback_agent: Optional[Literal["database", "excel", "chart"]] = None
    nl_query: str
    chart_type: Optional[str] = None
    table_hint: Optional[str] = None
    file_format: Optional[str] = None
    semantic_retrieval: bool = False
    agent_type: Optional[str] = None
    # Minimum permission needed to execute this route. Derived deterministically
    # from ``route``; not classified by the LLM.
    access_level: Optional[AccessLevel] = None

    def to_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["orchestrator_routes"] = list(ORCHESTRATOR_ROUTES)
        return d


class IntentService:
    """Classifies user query into workflow selection or fallback agent."""

    def __init__(
        self,
        llm: OpenAI = None,
        model: str = "gpt-4o",
    ):
        self.llm = llm or OpenAI()
        self.model = model

    def _build_prompt(self) -> str:
        """Build the classification prompt with current workflow descriptions."""
        return _INTENT_CLASSIFICATION_PROMPT.format(
            workflow_descriptions=get_workflow_descriptions(),
            connect_disconnect_reply=_CONNECT_DISCONNECT_UI_REPLY,
        )

    def _build_user_content(
        self,
        prompt: str,
        conversation_context: Optional[Sequence[Dict[str, Any]]] = None,
        conversation_summary: Optional[str] = None,
    ) -> str:
        """Build user payload for intent classification from history + latest turn."""
        summary = (conversation_summary or "").strip()
        if not conversation_context and not summary:
            return prompt

        rows: List[str] = []
        # Keep context short for routing; summary carries older details.
        for msg in conversation_context[-INTENT_CONTEXT_TURNS:]:
            role = str(msg.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            rows.append(f"{role}: {content}")

        payload_parts: List[str] = [
            "Use conversation context to resolve follow-up references.\n\n"
        ]
        if summary:
            payload_parts.append("[Running summary]\n" + summary + "\n\n")
        if rows:
            payload_parts.append("[Conversation context]\n" + "\n".join(rows) + "\n\n")
        payload_parts.append("[Latest user message]\n" + prompt)
        return "".join(payload_parts)

    async def classify(
        self,
        prompt: str,
        available_agents: List[str] = None,
        conversation_context: Optional[Sequence[Dict[str, Any]]] = None,
        conversation_summary: Optional[str] = None,
    ) -> IntentResult:
        """Classify user query into workflow or fallback agent.

        Args:
            prompt: User's input message
            available_agents: List of agent IDs available (e.g. ["database", "excel", "chart"])
            conversation_context: Optional recent user/assistant turns for multi-turn routing
            conversation_summary: Optional running summary for long conversations

        Returns:
            IntentResult with ``route`` (one of six branches), derived ``workflow_id`` /
            ``fallback_agent``, and ``orchestrator_routes`` catalog on ``to_dict()``.
        """
        logger.info(f"[IntentService] Classifying: {prompt[:50]}...")
        user_content = self._build_user_content(prompt, conversation_context, conversation_summary)

        response = self.llm.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._build_prompt(),
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        raw_content = response.choices[0].message.content or ""
        logger.info(f"[IntentService] Raw model JSON: {raw_content}")

        try:
            result = json.loads(raw_content)
        except Exception:
            logger.exception("[IntentService] Failed to parse model JSON; using safe fallback")
            result = {
                "needs_clarification": False,
                "clarification_question": None,
                "route": "db_general",
                "nl_query": prompt,
                "chart_type": None,

                "table_hint": None,
                "file_format": None,
                "semantic_retrieval": False,
            }

        nl_query = str(result.get("nl_query") or prompt).strip() or prompt
        available = {a.lower().strip() for a in (available_agents or [])}

        needs_clarification = bool(result.get("needs_clarification"))
        clarification_question_raw = result.get("clarification_question")
        clarification_question = (
            str(clarification_question_raw).strip()
            if isinstance(clarification_question_raw, str)
            else None
        )
        if needs_clarification and not clarification_question:
            clarification_question = (
                "Could you clarify what you'd like to do next?"
            )

        route: Optional[OrchestratorRoute]
        workflow_id: Optional[str]
        fallback_agent: Optional[str]
        agent_type: Optional[str]

        if needs_clarification:
            route = None
            workflow_id, fallback_agent, agent_type = (None, None, None)
        else:
            route = _resolve_orchestrator_route(result, nl_query)
            route = _adjust_route_for_available(route, available)
            workflow_id, fallback_agent, agent_type = _route_to_workflow_fields(route)

        intent_result = IntentResult(
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            route=route,
            workflow_id=workflow_id,
            fallback_agent=(fallback_agent if isinstance(fallback_agent, str) else None),
            agent_type=(agent_type if isinstance(agent_type, str) else None),
            nl_query=nl_query,
            chart_type=(str(result["chart_type"]).strip() if result.get("chart_type") else None),

            table_hint=(str(result["table_hint"]).strip() if result.get("table_hint") else None),
            file_format=(str(result["file_format"]).strip().lower() if result.get("file_format") else None),
            semantic_retrieval=bool(result.get("semantic_retrieval")),
            access_level=(ROUTE_ACCESS_LEVEL.get(route) if route else None),
        )

        logger.info(
            "[IntentService] Result: needs_clarification=%s, route=%s, workflow_id=%s, fallback_agent=%s, agent_type=%s",
            intent_result.needs_clarification,
            intent_result.route,
            intent_result.workflow_id,
            intent_result.fallback_agent,
            intent_result.agent_type,
        )
        return intent_result

    def has_workflow(self, workflow_id: str) -> bool:
        """Check if a workflow ID exists."""
        return workflow_id in get_workflow_ids()

    def get_workflow(self, workflow_id: str) -> dict | None:
        """Get workflow config by ID."""
        return get_workflow_by_id(workflow_id)


def _route_aliases(raw: str) -> str:
    s = raw.lower().strip()
    aliases = {
        "readonly": "db_readonly",
        "create_table": "db_create_table",
        "mutation": "db_mutation",
        "db_read_only": "db_readonly",
        "db-readonly": "db_readonly",
        "db_create": "db_create_table",
        "db_mutation_workflow": "db_mutation",
        "general_db": "db_general",
        "db_general": "db_general",
        "db_agent": "db_general",
        "database": "db_general",
    }
    return aliases.get(s, s)


def _resolve_orchestrator_route(result: dict, nl_query: str) -> OrchestratorRoute:
    """Pick canonical route from model JSON (or legacy workflow_id / fallback)."""
    raw_route = result.get("route")
    if raw_route is not None:
        s = _route_aliases(str(raw_route))
        if s in _VALID_ORCHESTRATOR_ROUTES:
            return s  # type: ignore[return-value]

    wf = result.get("workflow_id")
    if wf == "db_readonly":
        return "db_readonly"
    if wf == "db_create_table":
        return "db_create_table"
    if wf == "db_mutation":
        return "db_mutation"
    if wf == "excel_analyze":
        return "excel"
    if wf == "chart_render":
        return "chart"
    if wf and str(wf).startswith("excel"):
        return "excel"
    if wf and str(wf).startswith("chart"):
        return "chart"
    valid_ids = get_workflow_ids()
    if wf and wf in valid_ids:
        mapped = get_workflow_by_id(str(wf))
        if mapped:
            at = mapped.get("agent_type")
            if at == "excel":
                return "excel"
            if at == "chart":
                return "chart"
            if at == "database":
                return "db_general"

    fb = _normalize_fallback_agent(result.get("fallback_agent"))
    if fb == "excel":
        return "excel"
    if fb == "chart":
        return "chart"
    if fb == "database":
        return "db_general"

    inferred = _infer_fallback_agent({**result, "nl_query": nl_query}, nl_query)
    if inferred == "excel":
        return "excel"
    if inferred == "chart":
        return "chart"
    return "db_general"


def _adjust_route_for_available(route: OrchestratorRoute, available: set[str]) -> OrchestratorRoute:
    """If excel/chart agent is missing, fall back to general database when possible."""
    if not available:
        return route
    if route in ("db_readonly", "db_create_table", "db_mutation", "db_general"):
        if "database" not in available:
            logger.warning(
                "[IntentService] route=%s but no database agent in %s — keeping route",
                route,
                available,
            )
        return route
    if route == "excel" and "excel" not in available:
        return "db_general" if "database" in available else route
    if route == "chart" and "chart" not in available:
        return "db_general" if "database" in available else route
    return route


def _route_to_workflow_fields(route: OrchestratorRoute) -> tuple[Optional[str], Optional[str], str]:
    """Derive registry workflow_id + fallback_agent + agent_type from flat route."""
    if route == "db_readonly":
        return "db_readonly", None, "database"
    if route == "db_create_table":
        return "db_create_table", None, "database"
    if route == "db_mutation":
        return "db_mutation", None, "database"
    if route == "db_general":
        return None, "database", "database"
    if route == "excel":
        return "excel_analyze", None, "excel"
    if route == "chart":
        return "chart_render", None, "chart"
    return None, "database", "database"


def _normalize_fallback_agent(value: Any) -> Optional[str]:
    """Map model output to one of database | excel | chart."""
    if value is None:
        return None
    s = str(value).lower().strip()
    if s in _VALID_FALLBACK_AGENTS:
        return s
    aliases = {
        "db": "database",
        "postgres": "database",
        "postgresql": "database",
        "sqlite": "database",
        "sql": "database",
        "sheet": "excel",
        "spreadsheet": "excel",
        "xlsx": "excel",
        "xls": "excel",
        "csv": "excel",
        "charts": "chart",
        "plot": "chart",
        "graph": "chart",
        "viz": "chart",
        "visualization": "chart",
    }
    return aliases.get(s)


def _infer_fallback_agent(result: dict, nl_query: str) -> str:
    """Heuristic agent pick when workflow_id is null and model omitted fallback_agent."""
    if result.get("chart_type"):
        return "chart"
    q = (nl_query or "").lower()
    if any(
        w in q
        for w in (
            "chart",
            "plot",
            "graph",
            "visualization",
            "biểu đồ",
            "đồ thị",
        )
    ):
        return "chart"
    if any(
        w in q
        for w in (
            "excel",
            "xlsx",
            "csv",
            "spreadsheet",
            "export file",
            "download file",
            "sheet",
        )
    ):
        return "excel"
    return "database"


