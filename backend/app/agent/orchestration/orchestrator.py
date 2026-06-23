"""SINGLETON orchestrator — no spawning, no per-user cache.

Per-request state lives in the ContextVar (set by the chat layer before calling). The orchestrator only
holds backends (stateless): InProcess for db/chart, HTTP for excel.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.agent import prompts
from app.agent.context import get_ctx, get_db
from app.agent.graph.create_table_workflow import CreateTableWorkflow
from app.agent.graph.mutation_workflow import MutationWorkflow
from app.agent.graph.readonly_workflow import ReadOnlyWorkflow
from app.agent.loop import run_tool_loop
from app.agent.orchestration import intent as intent_mod
from app.agent.orchestration import normalize as normalize_mod
from app.agent.tools.backends import ExcelHttpBackend, InProcessBackend
from app.agent.tools.chart_tools import CHART_TOOL_NAMES
from app.agent.tools.db_tools import DB_TOOL_NAMES
from app.config import get_settings

logger = logging.getLogger("agent.orchestrator")

# Tool-loop routes keep only the most recent turns (sliding window) instead of summarizing —
# context windows are large and normalize() already folds earlier references into the query.
_MAX_HISTORY_TURNS = 10

# Async progress callback (streamed to the client as SSE stages). Default no-op.
StageCb = Callable[[str], Awaitable[None]]


async def _noop_stage(_message: str) -> None:
    return None


@dataclass
class ChatResult:
    response: str
    route: str | None = None
    requires_approval: bool = False
    pending_sql: str | None = None
    needs_clarification: bool = False
    tool_events: list[dict] = field(default_factory=list)
    action_id: str | None = None        # gated-action UUID (create_table / mutation)
    action_state: str | None = None     # 'pending' | 'executed' | 'cancelled' | 'failed'


def _action_state_from_output(out: dict) -> str | None:
    """Lifecycle state of a gated action, derived from the workflow output type. The service
    persists this to sql_actions so the FE reads action state from ONE source (the table)."""
    t = out.get("type")
    if t == "schema_preview":
        return "cancelled" if out.get("cancelled") else "pending"
    if t == "sql_statement":
        return "pending"
    if t == "execution_complete":
        return "executed"
    if t == "error" and out.get("sql"):
        return "failed"
    return None


def _events_from_output(out: dict) -> list[dict]:
    """Convert workflow output → tool_events for the frontend (SQL preview / schema editor)."""
    t = out.get("type")
    # Pending mutation preview → a 'sql_preview' event carrying the SQL + its kind so the FE
    # shows an Execute button (NOT executed). type_sql lets the FE auto-run DQL but gate DML/DDL.
    if t == "sql_statement" and out.get("sql"):
        return [{
            "tool": "execute_query",
            "type": "sql_preview",
            "payload": {"sql": out["sql"], "type_sql": out.get("sql_kind") or "DML",
                        "actionId": out.get("action_id")},
        }]
    # Statement that actually ran → 'sql_execution' (green "Query executed").
    if t == "execution_complete" and out.get("sql"):
        return [{
            "tool": "execute_query",
            "type": "sql_execution",
            "payload": {"sql": out["sql"], "result": out.get("message", ""),
                        "actionId": out.get("action_id")},
        }]
    # read-only SELECT → structured result the FE renders as a table (server renders NOTHING).
    if t == "query_result":
        r = out.get("result") or {}
        return [{
            "tool": "execute_query",
            "type": "query_result",
            "payload": {"sql": out.get("sql") or "", "columns": r.get("columns") or [],
                        "rows": r.get("rows") or []},
        }]
    # create_table schema preview → structured event the FE editor reads (no text marker).
    if t == "schema_preview" and out.get("columns"):
        cols = out["columns"]
        pk = next((c.get("variable") for c in cols if c.get("primaryKey")), None)
        return [{
            "tool": "show_create_table_schema",
            "type": "schema_preview",
            "payload": {
                "actionId": out.get("action_id"),
                "tableName": out.get("table") or "",
                "tableDescription": out.get("tableDescription") or "",
                "primaryKey": pk,
                "columns": [{
                    "variable": c.get("variable", ""),
                    "type": c.get("type", ""),
                    "primaryKey": bool(c.get("primaryKey")),
                    "notNull": bool(c.get("notNull")),
                    "unique": bool(c.get("unique")),
                    "defaultValue": c.get("defaultValue"),
                    "description": c.get("description") or "",
                    "enumValues": c.get("enumValues") if isinstance(c.get("enumValues"), list) else None,
                } for c in cols],
            },
        }]
    return []


def _events_from_tool_loop(events) -> list[dict]:
    """Map raw tool-loop ToolEvents → the structured FE contract ({tool, type, payload}).

    Doing this here (instead of only in the router) means the SAME structured events are both
    streamed to the client AND persisted — so charts/SQL survive a history reload.
    """
    out: list[dict] = []
    for e in events or []:
        if e.tool == "generate_chart":
            if e.is_error:
                continue
            out.append({"tool": e.tool, "type": "chart", "payload": {"spec": e.result}})
        elif e.tool == "execute_query":
            out.append({"tool": e.tool, "type": "sql_execution",
                        "payload": {"sql": (e.args or {}).get("query"), "result": e.result}})
        else:
            out.append({"tool": e.tool, "type": "tool_result", "payload": {"result": e.result}})
    return out


class Orchestrator:
    def __init__(self, excel_mcp_url: str):
        self.db_backend = InProcessBackend(DB_TOOL_NAMES)
        self.chart_backend = InProcessBackend(CHART_TOOL_NAMES)
        self.excel_backend = ExcelHttpBackend(excel_mcp_url)
        self.mutation_wf = MutationWorkflow()
        self.create_table_wf = CreateTableWorkflow()
        self.readonly_wf = ReadOnlyWorkflow()

    async def warmup(self) -> None:
        try:
            await self.excel_backend.refresh()
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load excel-server tools (%s) — will retry on use.", e)

    async def normalize(self, user_message: str, history: list[dict] | None = None) -> str:
        """Resolve references (against recent history) + translate to English → a standalone,
        route-agnostic query. Run this BEFORE classify; pass the result to both."""
        return await normalize_mod.normalize(user_message, history or [])

    async def classify(self, query: str) -> intent_mod.Intent:
        """Classify an already-normalized query (used for permission gating before running)."""
        return await intent_mod.classify(query)

    async def process_query(
        self,
        user_message: str,
        intent: intent_mod.Intent,
        history: list[dict] | None = None,
        on_stage: StageCb | None = None,
    ) -> ChatResult:
        """Execute the branch already chosen by `intent` (classified once by the caller).

        The caller handles needs_clarification before calling — `intent` here always has a route.
        `on_stage` (optional) streams human-readable progress stages to the client.
        """
        history = history or []
        emit = on_stage or _noop_stage
        engine = get_db().engine
        route = intent.route or "db_general"

        if route in ("db_mutation", "db_create_table"):
            session_id = get_ctx().session_id or "anon"
            wf = self.create_table_wf if route == "db_create_table" else self.mutation_wf
            # user_message is the normalized standalone query (see Orchestrator.normalize).
            state, pending = await wf.run(session_id, user_message, engine, on_stage=emit)
            out = state.get("output") or {}
            return ChatResult(
                response=str(out.get("message") or ""),
                route=route,
                requires_approval=pending,
                tool_events=_events_from_output(out),
                action_id=out.get("action_id"),
                action_state=_action_state_from_output(out),
            )

        if route == "db_readonly":
            session_id = get_ctx().session_id or "anon"
            state = await self.readonly_wf.run(session_id, user_message, engine, on_stage=emit)
            out = state.get("output") or {}
            return ChatResult(response=str(out.get("message") or ""), route=route,
                              tool_events=_events_from_output(out))
        
        # Sliding window: keep only the most recent turns (no summarization).
        history = history[-_MAX_HISTORY_TURNS:]
        if route == "excel":
            if not self.excel_backend.list_tools_openai():
                await self.excel_backend.refresh()
            res = await run_tool_loop(
                system_prompt=prompts.excel_system_prompt(),
                history=history, user_message=user_message, backends=[self.excel_backend],
            )
        elif route == "chart":
            res = await run_tool_loop(
                system_prompt=prompts.chart_system_prompt(engine),
                history=history, user_message=user_message,
                backends=[self.chart_backend, self.db_backend],
            )
        else:  # db_general (tool loop chung)
            res = await run_tool_loop(
                system_prompt=prompts.db_system_prompt(engine),
                history=history, user_message=user_message, backends=[self.db_backend],
            )

        return ChatResult(
            response=res.text, route=route,
            tool_events=_events_from_tool_loop(res.tool_events),
        )

    async def resume(
        self, session_id: str, approved: bool, edited_schema: dict | None = None
    ) -> ChatResult:
        """Resume the workflow awaiting approval (mutation or create_table). The SQL lives in the
        server-side checkpoint, the client does NOT send SQL → cannot inject.

        For create_table the client MAY send `edited_schema` (structured columns); the workflow
        rebuilds + re-verifies the CREATE SQL from it. Mutation ignores it (resume is a bare bool).
        Routes to the correct workflow by checking which checkpoint is still pending."""
        engine = get_db().engine
        ct_pending = await self.create_table_wf.pending(session_id)
        mut_pending = await self.mutation_wf.pending(session_id)
        if not ct_pending and not mut_pending:
            return ChatResult(response="There is no pending action to confirm.", route="db_general")

        if ct_pending:
            wf, route = self.create_table_wf, "db_create_table"
            resume_val: object = {"approved": approved, "schema": edited_schema}
        else:
            wf, route = self.mutation_wf, "db_mutation"
            resume_val = approved
        state, pending = await wf.run(session_id, "", engine, resume=resume_val)
        out = state.get("output") or {}
        return ChatResult(
            response=str(out.get("message") or ""),
            route=route,
            requires_approval=pending,
            tool_events=_events_from_output(out),
            action_id=out.get("action_id"),
            action_state=_action_state_from_output(out),
        )


_singleton: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _singleton
    if _singleton is None:
        _singleton = Orchestrator(get_settings().excel_mcp_url)
    return _singleton
