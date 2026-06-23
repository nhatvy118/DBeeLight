"""Mutation workflow (LangGraph) — INSERT/UPDATE/DELETE/ALTER/DROP with APPROVAL.

Unlike the skeleton: the pending SQL lives in the **server-side checkpoint**; approve is just a
boolean resume (the client does NOT send SQL) → closes the SQL-injection hole.

Flow: SCHEMA_DISCOVERY → SQL_PREVIEW → APPROVAL(interrupt) → EXECUTION → DONE
"""
from __future__ import annotations

import logging
import uuid
from typing import cast

import sqlglot
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlglot import exp

from app.agent.graph import dbtools
from app.agent.graph.checkpointer import get_async_checkpointer
from app.agent.graph.schema_context import enrich_schema_text
from app.agent.graph.sql_gen import generate_sql
from app.agent.graph.stages import StageCb, stream_stages
from app.agent.graph.state import (
    OUTPUT_ERROR,
    OUTPUT_EXECUTION,
    OUTPUT_SQL_STATEMENT,
    AgentState,
    StageType,
    create_initial_state,
)

logger = logging.getLogger("agent.graph.mutation")



async def _schema_discovery(state: AgentState) -> AgentState:
    schema_text = await enrich_schema_text(mode="write")  # full: includes default/UNIQUE
    return {**state, "schema_text": schema_text}


async def _sql_preview(state: AgentState) -> AgentState:
    engine = state.get("engine", "sqlite")
    schema = state.get("schema_text") or ""
    sql, err, kind = await generate_sql(state.get("user_message", ""), schema, engine, mode="write")
    if err:
        return {**state, "sql": None,
                "output": {"type": OUTPUT_ERROR, "message": f"Could not generate valid SQL.\n{err}"}}

    # Ship the SQL + structured affected-rows preview as DATA; the FE renders both (same as the
    # query_result path). The server does NOT format a table here.
    preview = await _affected_rows(sql, engine)
    action_id = state.get("action_id") or str(uuid.uuid4())
    return {
        **state, "sql": sql, "action_id": action_id,
        "output": {"type": OUTPUT_SQL_STATEMENT, "executed": False, "sql": sql, "action_id": action_id,
                   "message": f"```sql\n{sql}\n```", "sql_kind": kind, "preview": preview},
    }


async def _affected_rows(sql: str, engine: str) -> dict | None:
    """For UPDATE/DELETE, return the rows that WOULD be affected as structured data
    ({columns, rows, rowcount}) by running a read-only SELECT with the same target table + WHERE.
    None when there's nothing to preview.

    Built from the parsed AST (not regex / string interpolation), so quoted identifiers,
    subqueries and complex WHEREs are handled correctly and nothing is concatenated into SQL.
    The FE renders the table; the server does no formatting."""
    dialect = "sqlite" if engine == "sqlite" else "postgres"
    try:
        nodes = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:  # noqa: BLE001
        return None
    node = next((n for n in nodes if isinstance(n, (exp.Update, exp.Delete))), None)
    if node is None:
        return None
    table = node.args.get("this")  # target table of the UPDATE/DELETE
    if table is None:
        return None
    select = exp.select("*").from_(table.copy())
    where = node.args.get("where")
    if where is not None:
        select = select.where(where.this.copy())  # same condition → same rows
    select = select.limit(50)
    try:
        res = await dbtools.run(select.sql(dialect=dialect))
    except Exception:  # noqa: BLE001 — preview is best-effort; never block the approval on it
        return None
    return res.to_dict()


async def _approval(state: AgentState) -> AgentState:
    # SQL lives in state (server-side checkpoint); the client only sends a bool decision.
    ok = interrupt({"stage": StageType.SQL_PREVIEW.value, "output": state.get("output")})
    if not ok:
        return {**state, "approved": False,
                "output": {**(state.get("output") or {}), "action_id": state.get("action_id"),
                           "message": "SQL execution cancelled.", "cancelled": True}}
    return {**state, "approved": True}


async def _execution(state: AgentState) -> AgentState:
    if not state.get("approved"):
        return {**state, "output": {"type": "execution_skipped", "message": "Cancelled."}}
    sql = state.get("sql") or ""
    try:
        res = await dbtools.run(sql)
        msg = f"Executed successfully. ({res.rowcount} rows affected)"
        out = {"type": OUTPUT_EXECUTION, "sql": sql, "message": msg, "action_id": state.get("action_id")}
    except Exception as e:  # noqa: BLE001
        out = {"type": OUTPUT_ERROR, "sql": sql, "action_id": state.get("action_id"),
               "message": f"The SQL couldn’t run: {dbtools.clean_db_error(str(e))}."}
    return {**state, "output": out}


async def _done(state: AgentState) -> AgentState:
    return state  # terminal node: converge edges → END (no state change)


def _route_after_schema(state: AgentState) -> str:
    if (state.get("output") or {}).get("type") == OUTPUT_ERROR:
        return StageType.DONE.value
    return StageType.SQL_PREVIEW.value


def _route_after_preview(state: AgentState) -> str:
    if (state.get("output") or {}).get("type") == OUTPUT_ERROR:
        return StageType.DONE.value
    return StageType.APPROVAL.value


class MutationWorkflow:
    def __init__(self):
        self._graph = None

    async def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node(StageType.SCHEMA_DISCOVERY.value, _schema_discovery)
            g.add_node(StageType.SQL_PREVIEW.value, _sql_preview)
            g.add_node(StageType.APPROVAL.value, _approval)
            g.add_node(StageType.EXECUTION.value, _execution)
            g.add_node(StageType.DONE.value, _done)
            g.set_entry_point(StageType.SCHEMA_DISCOVERY.value)
            g.add_conditional_edges(StageType.SCHEMA_DISCOVERY.value, _route_after_schema,
                                    {StageType.SQL_PREVIEW.value: StageType.SQL_PREVIEW.value,
                                     StageType.DONE.value: StageType.DONE.value})
            g.add_conditional_edges(StageType.SQL_PREVIEW.value, _route_after_preview,
                                    {StageType.APPROVAL.value: StageType.APPROVAL.value,
                                     StageType.DONE.value: StageType.DONE.value})
            g.add_edge(StageType.APPROVAL.value, StageType.EXECUTION.value)
            g.add_edge(StageType.EXECUTION.value, StageType.DONE.value)
            g.add_edge(StageType.DONE.value, END)
            self._graph = g.compile(checkpointer=await get_async_checkpointer())
        return self._graph

    def _cfg(self, session_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": f"{session_id}:mutation"}}

    async def pending(self, session_id: str) -> bool:
        graph = await self._compiled()
        snap = await graph.aget_state(self._cfg(session_id))
        return bool(getattr(snap, "next", None))

    async def run(
        self, session_id: str, user_message: str, engine: str, *, resume=None,
        on_stage: StageCb | None = None,
    ) -> tuple[AgentState, bool]:
        graph = await self._compiled()
        cfg = self._cfg(session_id)
        graph_input = create_initial_state(user_message, engine) if resume is None else Command(resume=resume)
        # astream emits a stage per node as it runs (stops at the APPROVAL interrupt); the
        # snapshot below still provides the pending/next flag from the checkpoint.
        await stream_stages(graph, graph_input, on_stage, cfg)
        snap = await graph.aget_state(cfg)
        state = cast(AgentState, dict(snap.values) if snap and snap.values else {})
        pending = bool(getattr(snap, "next", None))  # a node is waiting (interrupt) → needs approval
        return state, pending
