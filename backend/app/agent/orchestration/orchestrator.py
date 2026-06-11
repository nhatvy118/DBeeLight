"""SINGLETON orchestrator — no spawning, no per-user cache.

Per-request state lives in the ContextVar (set by the chat layer before calling). The orchestrator only
holds backends (stateless): InProcess for db/chart, HTTP for excel.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from app.agent import prompts
from app.agent.context import get_ctx, get_db
from app.agent.graph.create_table_workflow import CreateTableWorkflow
from app.agent.graph.mutation_workflow import MutationWorkflow
from app.agent.graph.readonly_workflow import ReadOnlyWorkflow
from app.agent.loop import run_tool_loop
from app.agent.orchestration import intent as intent_mod
from app.agent.tools.backends import ExcelHttpBackend, InProcessBackend
from app.agent.tools.chart_tools import CHART_TOOL_NAMES
from app.agent.tools.db_tools import DB_TOOL_NAMES
from app.config import get_settings

logger = logging.getLogger("agent.orchestrator")


@dataclass
class ChatResult:
    response: str
    route: str | None = None
    requires_approval: bool = False
    pending_sql: str | None = None
    needs_clarification: bool = False
    tool_events: list[dict] = field(default_factory=list)


def _events_from_output(out: dict) -> list[dict]:
    """Convert workflow output → tool_events for the frontend (SQL preview / schema editor)."""
    t = out.get("type")
    if t in ("sql_statement", "execution_complete") and out.get("sql"):
        return [{"tool": "execute_query", "args": {"query": out["sql"]},
                 "result": out.get("message", ""), "is_error": False}]
    # create_table schema preview → structured event the FE editor reads (no text marker).
    if t == "schema_preview" and out.get("columns"):
        cols = out["columns"]
        pk = next((c.get("name") for c in cols if c.get("pk")), None)
        return [{
            "tool": "show_create_table_schema",
            "type": "schema_preview",
            "payload": {
                "tableName": out.get("table") or "",
                "primaryKey": pk,
                "columns": [{"variable": c.get("name", ""), "type": c.get("type", "")} for c in cols],
            },
        }]
    return []


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

    def classify(
        self, user_message: str, history: list[dict] | None = None, summary: str = ""
    ) -> intent_mod.Intent:
        """Classify intent (used for permission gating before running)."""
        return intent_mod.classify(user_message, history or [], summary=summary)

    async def process_query(
        self,
        user_message: str,
        intent: intent_mod.Intent,
        history: list[dict] | None = None,
        summary: str = "",
    ) -> ChatResult:
        """Execute the branch already chosen by `intent` (classified once by the caller).

        The caller handles needs_clarification before calling — `intent` here always has a route.
        """
        history = history or []
        engine = get_db().engine

        def _sp(base: str) -> str:
            return f"[Previous conversation summary]\n{summary}\n\n{base}" if summary else base

        route = intent.route or "db_general"

        if route in ("db_mutation", "db_create_table"):
            session_id = get_ctx().session_id or "anon"
            wf = self.create_table_wf if route == "db_create_table" else self.mutation_wf
            state, pending = await wf.run(session_id, user_message + intent.nl_query, engine)
            out = state.get("output") or {}
            return ChatResult(
                response=str(out.get("message") or ""),
                route=route,
                requires_approval=pending,
                tool_events=_events_from_output(out),
            )

        if route == "db_readonly":
            session_id = get_ctx().session_id or "anon"
            state = await self.readonly_wf.run(session_id, user_message, engine)
            out = state.get("output") or {}
            return ChatResult(response=str(out.get("message") or ""), route=route,
                              tool_events=_events_from_output(out))

        if route == "excel":
            if not self.excel_backend.list_tools_openai():
                await self.excel_backend.refresh()
            res = await run_tool_loop(
                system_prompt=_sp(prompts.excel_system_prompt()),
                history=history, user_message=user_message, backends=[self.excel_backend],
            )
        elif route == "chart":
            res = await run_tool_loop(
                system_prompt=_sp(prompts.chart_system_prompt(engine)),
                history=history, user_message=user_message,
                backends=[self.chart_backend, self.db_backend],
            )
        else:  # db_general (tool loop chung)
            res = await run_tool_loop(
                system_prompt=_sp(prompts.db_system_prompt(engine)),
                history=history, user_message=user_message, backends=[self.db_backend],
            )

        return ChatResult(
            response=res.text, route=route,
            tool_events=[asdict(e) for e in res.tool_events],
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
        wf = self.mutation_wf
        route = "db_mutation"
        resume_val: object = approved
        if await self.create_table_wf.pending(session_id):
            wf, route = self.create_table_wf, "db_create_table"
            resume_val = {"approved": approved, "schema": edited_schema}
        state, pending = await wf.run(session_id, "", engine, resume=resume_val)
        out = state.get("output") or {}
        return ChatResult(
            response=str(out.get("message") or ""),
            route=route,
            requires_approval=pending,
            tool_events=_events_from_output(out),
        )


_singleton: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _singleton
    if _singleton is None:
        _singleton = Orchestrator(get_settings().excel_mcp_url)
    return _singleton
