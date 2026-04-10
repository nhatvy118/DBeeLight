"""Intent Service — classifies user queries into workflow + agent selection.

Single LLM call returns everything needed for orchestration.
Uses workflow_registry to provide structured descriptions for selection.
Falls back to general-purpose agent if no workflow matches.
"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel

from mcp_agent.orchestration.workflow_registry import (
    get_workflow_descriptions,
    get_workflow_ids,
    get_workflow_by_id,
)

logger = logging.getLogger(__name__)

_VALID_FALLBACK_AGENTS = frozenset({"database", "excel", "superset"})

# Six orchestrator branches at the same level: three DB LangGraphs + three agents.
OrchestratorRoute = Literal[
    "db_readonly",
    "db_create_table",
    "db_mutation",
    "database",
    "excel",
    "superset",
]

ORCHESTRATOR_ROUTES: List[Dict[str, str]] = [
    {"id": "db_readonly", "kind": "workflow", "label": "Database read-only (SELECT, schema, list/describe tables, connect/disconnect, …)"},
    {"id": "db_create_table", "kind": "workflow", "label": "Database create table"},
    {"id": "db_mutation", "kind": "workflow", "label": "Database mutation (INSERT/UPDATE/DELETE/ALTER/DROP/…)"},
    {"id": "database", "kind": "agent", "label": "Database agent (general tool loop)"},
    {"id": "excel", "kind": "agent", "label": "Excel agent"},
    {"id": "superset", "kind": "agent", "label": "Superset agent"},
]

_VALID_ORCHESTRATOR_ROUTES = frozenset(r["id"] for r in ORCHESTRATOR_ROUTES)

_INTENT_CLASSIFICATION_PROMPT = """You are an orchestration router. Pick exactly ONE branch for the user request.

**Decision order (important):**
- For anything database-related, decide in this order: first try **1 → 2 → 3** (the three structured DB workflows). Only if the request clearly fits NONE of them, use **4** (general Database Agent).
- Non-database topics: use **5** or **6** when appropriate.

Branches:

1) "db_readonly" — Read-only: SELECT, list/describe tables, schema exploration, aggregates without modifying data; **connect/disconnect**; host/port/credentials; SQLite path; `connect_db` / `connect_sqlite`.
2) "db_create_table" — CREATE TABLE / define new table structure.
3) "db_mutation" — INSERT, UPDATE, DELETE, ALTER, DROP, data export/mutation workflows, etc.
4) "database" — ONLY when the request is about databases but does **not** fit 1–3 (vague help, troubleshooting, conversational DB Q&A with no clear readonly/create/mutation shape).
5) "excel" — Spreadsheets, CSV/XLSX, rows/columns, analyze/transform Excel files.
6) "superset" — Charts, dashboards, BI, Superset visualization.

Reference (registry workflows for wording only):
{workflow_descriptions}

Return strict JSON with:
- "needs_clarification": REQUIRED boolean — true ONLY if the user request is ambiguous and you cannot safely choose a route yet.
- "clarification_question": REQUIRED string or null — if needs_clarification is true, ask ONE concise follow-up question to disambiguate; otherwise null.
- "route": REQUIRED when needs_clarification=false — exactly one of: "db_readonly" | "db_create_table" | "db_mutation" | "database" | "excel" | "superset"
- "nl_query": normalized natural-language query
- "chart_type": chart hint if visualization requested, else null
- "requires_export": true if user asks export/download file, else false
- "table_hint": table/entity hint if mentioned, else null
- "file_format": output/input file format if present (csv, xlsx, json, etc.), else null

Return JSON only."""


class IntentResult(BaseModel):
    """Result of intent classification."""

    # Canonical choice among the six orchestrator branches (same level).
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    route: Optional[OrchestratorRoute] = None
    workflow_id: Optional[str] = None
    fallback_agent: Optional[Literal["database", "excel", "superset"]] = None
    nl_query: str
    chart_type: Optional[str] = None
    requires_export: bool = False
    table_hint: Optional[str] = None
    file_format: Optional[str] = None
    agent_type: Optional[str] = None

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
            workflow_descriptions=get_workflow_descriptions()
        )

    async def classify(
        self,
        prompt: str,
        available_agents: List[str] = None,
    ) -> IntentResult:
        """Classify user query into workflow or fallback agent.

        Args:
            prompt: User's input message
            available_agents: List of agent IDs available (e.g. ["database", "excel", "superset"])

        Returns:
            IntentResult with ``route`` (one of six branches), derived ``workflow_id`` /
            ``fallback_agent``, and ``orchestrator_routes`` catalog on ``to_dict()``.
        """
        logger.info(f"[IntentService] Classifying: {prompt[:50]}...")

        response = self.llm.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._build_prompt(),
                },
                {
                    "role": "user",
                    "content": prompt
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
                "route": "database",
                "nl_query": prompt,
                "chart_type": None,
                "requires_export": False,
                "table_hint": None,
                "file_format": None,
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
            clarification_question = "Bạn có thể nói rõ bạn muốn làm gì tiếp theo không?"

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
            requires_export=bool(result.get("requires_export")),
            table_hint=(str(result["table_hint"]).strip() if result.get("table_hint") else None),
            file_format=(str(result["file_format"]).strip().lower() if result.get("file_format") else None),
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
        "general_db": "database",
        "db_general": "database",
        "db_agent": "database",
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
    if wf == "superset_chart":
        return "superset"
    if wf and str(wf).startswith("excel"):
        return "excel"
    if wf and str(wf).startswith("superset"):
        return "superset"
    valid_ids = get_workflow_ids()
    if wf and wf in valid_ids:
        mapped = get_workflow_by_id(str(wf))
        if mapped:
            at = mapped.get("agent_type")
            if at == "excel":
                return "excel"
            if at == "superset":
                return "superset"
            if at == "database":
                return "database"

    fb = _normalize_fallback_agent(result.get("fallback_agent"))
    if fb == "excel":
        return "excel"
    if fb == "superset":
        return "superset"
    if fb == "database":
        return "database"

    inferred = _infer_fallback_agent({**result, "nl_query": nl_query}, nl_query)
    if inferred == "excel":
        return "excel"
    if inferred == "superset":
        return "superset"
    return "database"


def _adjust_route_for_available(route: OrchestratorRoute, available: set[str]) -> OrchestratorRoute:
    """If excel/superset agent is missing, fall back to general database when possible."""
    if not available:
        return route
    if route in ("db_readonly", "db_create_table", "db_mutation", "database"):
        if "database" not in available:
            logger.warning(
                "[IntentService] route=%s but no database agent in %s — keeping route",
                route,
                available,
            )
        return route
    if route == "excel" and "excel" not in available:
        return "database" if "database" in available else route
    if route == "superset" and "superset" not in available:
        return "database" if "database" in available else route
    return route


def _route_to_workflow_fields(route: OrchestratorRoute) -> tuple[Optional[str], Optional[str], str]:
    """Derive registry workflow_id + fallback_agent + agent_type from flat route."""
    if route == "db_readonly":
        return "db_readonly", None, "database"
    if route == "db_create_table":
        return "db_create_table", None, "database"
    if route == "db_mutation":
        return "db_mutation", None, "database"
    if route == "database":
        return None, "database", "database"
    if route == "excel":
        return "excel_analyze", None, "excel"
    if route == "superset":
        return "superset_chart", None, "superset"
    return None, "database", "database"


def _normalize_fallback_agent(value: Any) -> Optional[str]:
    """Map model output to one of database | excel | superset."""
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
        "chart": "superset",
        "charts": "superset",
        "dashboard": "superset",
        "bi": "superset",
        "viz": "superset",
        "visualization": "superset",
    }
    return aliases.get(s)


def _infer_fallback_agent(result: dict, nl_query: str) -> str:
    """Heuristic agent pick when workflow_id is null and model omitted fallback_agent."""
    if result.get("chart_type"):
        return "superset"
    if bool(result.get("requires_export")):
        return "excel"
    ff = str(result.get("file_format") or "").lower().strip()
    if ff in {"xlsx", "xls", "csv"} or ff == "excel":
        return "excel"
    q = (nl_query or "").lower()
    if any(
        w in q
        for w in (
            "chart",
            "dashboard",
            "superset",
            "visualization",
            "biểu đồ",
            "đồ thị",
        )
    ):
        return "superset"
    if any(
        w in q
        for w in (
            "excel",
            "xlsx",
            "csv",
            "spreadsheet",
            "xuất file",
            "tải file",
            "sheet",
        )
    ):
        return "excel"
    return "database"
