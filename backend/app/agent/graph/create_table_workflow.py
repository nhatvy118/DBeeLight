"""CreateTable workflow (LangGraph) — 2 phases: review columns → create table.

Phase 1 (SCHEMA_PREVIEW): generate a column spec + CREATE TABLE SQL, show the column table for
the user to review data types (interrupt). Phase 2 (EXECUTION): run CREATE after approval.
"""
from __future__ import annotations

import json
import logging
import re

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from app.agent.graph import dbtools
from app.agent.graph.checkpointer import get_async_checkpointer
from app.agent.graph.sql_verification import tier1_static
from app.agent.graph.state import (
    OUTPUT_ERROR,
    OUTPUT_EXECUTION,
    OUTPUT_SCHEMA_PREVIEW,
    AgentState,
    StageType,
    create_initial_state,
)
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.create_table")


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    return re.sub(r"\n?```$", "", t).strip()


async def _schema_preview(state: AgentState) -> AgentState:
    engine = state.get("engine", "sqlite")
    existing = await dbtools.list_tables()
    client = get_llm()
    resp = client.chat.completions.create(
        model=get_settings().llm_model,
        messages=[
            {"role": "system", "content": (
                f"Design a new table for the request ({engine}). Return JSON: "
                '{"table": "...", "columns": [{"name": "...", "type": "...", "pk": bool}], '
                '"create_sql": "CREATE TABLE ..."}'
            )},
            {"role": "user", "content": state.get("user_message", "")},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        spec = json.loads(resp.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001
        spec = {}

    table = str(spec.get("table") or "").strip()
    if table and table.lower() in {t.lower() for t in existing}:
        return {**state, "current_stage": StageType.DONE.value,
                "output": {"type": OUTPUT_ERROR, "message": f"Table `{table}` already exists."}}

    cols = spec.get("columns") or []
    sql = _strip_fences(str(spec.get("create_sql") or ""))
    t1 = tier1_static(sql, engine)
    if not t1.ok or t1.kind != "DDL":
        return {**state, "current_stage": StageType.DONE.value,
                "output": {"type": OUTPUT_ERROR, "message": f"Invalid CREATE SQL: {t1.error or t1.kind}"}}

    lines = ["| Column | Type | PK |", "| --- | --- | --- |"]
    for c in cols:
        lines.append(f"| {c.get('name','')} | {c.get('type','')} | {'✓' if c.get('pk') else ''} |")
    body = "Review the column data types:\n\n" + "\n".join(lines) + f"\n\n```sql\n{sql}\n```\n\n_Click Execute to create the table._"
    return {**state, "sql": sql, "current_stage": StageType.SCHEMA_PREVIEW.value,
            "output": {"type": OUTPUT_SCHEMA_PREVIEW, "sql": sql, "message": body}}


async def _approval(state: AgentState) -> AgentState:
    ok = interrupt({"stage": StageType.SCHEMA_PREVIEW.value, "output": state.get("output")})
    if not ok:
        return {**state, "approved": False,
                "output": {**(state.get("output") or {}), "message": "Table creation cancelled.", "cancelled": True}}
    return {**state, "approved": True, "current_stage": StageType.EXECUTION.value}


async def _execution(state: AgentState) -> AgentState:
    if not state.get("approved"):
        return {**state, "output": {"type": "execution_skipped", "message": "Cancelled."}}
    sql = state.get("sql") or ""
    try:
        await dbtools.run(sql)
        out = {"type": OUTPUT_EXECUTION, "sql": sql, "message": "Table created successfully."}
    except Exception as e:  # noqa: BLE001
        out = {"type": OUTPUT_ERROR, "sql": sql, "message": f"Error creating table: {e}"}
    return {**state, "current_stage": StageType.DONE.value, "output": out}


def _route_after_preview(state: AgentState) -> str:
    if (state.get("output") or {}).get("type") == OUTPUT_ERROR:
        return StageType.DONE.value
    return "APPROVAL"


class CreateTableWorkflow:
    def __init__(self):
        self._graph = None

    async def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node("SCHEMA_PREVIEW", _schema_preview)
            g.add_node("APPROVAL", _approval)
            g.add_node("EXECUTION", _execution)
            g.add_node(StageType.DONE.value, lambda s: {**s, "current_stage": StageType.DONE.value})
            g.set_entry_point("SCHEMA_PREVIEW")
            g.add_conditional_edges("SCHEMA_PREVIEW", _route_after_preview,
                                    {"APPROVAL": "APPROVAL", StageType.DONE.value: StageType.DONE.value})
            g.add_edge("APPROVAL", "EXECUTION")
            g.add_edge("EXECUTION", StageType.DONE.value)
            g.add_edge(StageType.DONE.value, END)
            self._graph = g.compile(checkpointer=await get_async_checkpointer())
        return self._graph

    def _cfg(self, session_id: str) -> dict:
        return {"configurable": {"thread_id": f"{session_id}:create_table"}}

    async def pending(self, session_id: str) -> bool:
        graph = await self._compiled()
        snap = await graph.aget_state(self._cfg(session_id))
        return bool(getattr(snap, "next", None))

    async def run(self, session_id: str, user_message: str, engine: str, *, resume=None) -> tuple[AgentState, bool]:
        graph = await self._compiled()
        cfg = self._cfg(session_id)
        if resume is None:
            await graph.ainvoke(create_initial_state(session_id, user_message, engine), cfg)
        else:
            await graph.ainvoke(Command(resume=resume), cfg)
        snap = await graph.aget_state(cfg)
        state: AgentState = dict(snap.values) if snap and snap.values else {}
        return state, bool(getattr(snap, "next", None))
