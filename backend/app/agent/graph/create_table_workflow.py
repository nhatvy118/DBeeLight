"""CreateTable workflow (LangGraph) — 2 phases: review columns → create table.

Phase 1 (SCHEMA_PREVIEW): generate a column spec + CREATE TABLE SQL, show the column table for
the user to review data types (interrupt). Phase 2 (EXECUTION): run CREATE after approval.
"""
from __future__ import annotations

import json
import logging
import re
from typing import cast

from langchain_core.runnables import RunnableConfig
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


# --- Rebuild CREATE TABLE from the user-edited (structured) schema ---------------
# The columns come from the client editor, so identifiers/types are sanitized and the
# rebuilt SQL is re-verified by tier1_static (must be DDL) before it can run.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?$")
_DEFAULT_KEYWORDS = {"NULL", "TRUE", "FALSE", "CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"}


def _safe_ident(name: object) -> str:
    n = str(name or "").strip()
    if not _IDENT_RE.match(n):
        raise ValueError(f"invalid name {name!r}")
    return f'"{n}"'


def _safe_type(t: object) -> str:
    tt = str(t or "").strip()
    if not _TYPE_RE.match(tt):
        raise ValueError(f"invalid type {t!r}")
    return tt.upper()


def _safe_default(v: object) -> str:
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s  # numeric literal
    if s.upper() in _DEFAULT_KEYWORDS:
        return s.upper()
    return "'" + s.replace("'", "''") + "'"  # quoted string literal (escaped)


def _build_create_sql(table: object, columns: list[dict]) -> str:
    """Build a CREATE TABLE from the editor's structured columns. Raises ValueError on
    any unsafe identifier/type (defense-in-depth before tier1_static re-verifies)."""
    tbl = _safe_ident(table)
    defs: list[str] = []
    for c in columns:
        parts = [_safe_ident(c.get("variable") or c.get("name")), _safe_type(c.get("type"))]
        if c.get("primaryKey"):
            parts.append("PRIMARY KEY")
        if c.get("notNull"):
            parts.append("NOT NULL")
        if c.get("unique"):
            parts.append("UNIQUE")
        dv = c.get("defaultValue")
        if dv not in (None, ""):
            parts.append("DEFAULT " + _safe_default(dv))
        defs.append(" ".join(parts))
    if not defs:
        raise ValueError("no columns")
    return f"CREATE TABLE {tbl} (\n  " + ",\n  ".join(defs) + "\n)"


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
                "output": {"type": OUTPUT_ERROR, "message": f"Table `{table}` already exists. To create a new one, try a different name or delete the old one."}}

    cols = spec.get("columns") or []
    sql = _strip_fences(str(spec.get("create_sql") or ""))
    t1 = tier1_static(sql, engine)
    if not t1.ok or t1.kind != "DDL":
        return {**state, "current_stage": StageType.DONE.value,
                "output": {"type": OUTPUT_ERROR, "message": f"Invalid CREATE SQL: {t1.error or t1.kind}"}}

    # The column table is rendered by the FE schema editor (from the tool_event built in
    # _events_from_output), so the message body stays short — intro + SQL for reference.
    body = f"Review the column data types below, then create the table.\n\n```sql\n{sql}\n```"
    return {**state, "sql": sql, "current_stage": StageType.SCHEMA_PREVIEW.value,
            "output": {"type": OUTPUT_SCHEMA_PREVIEW, "sql": sql, "message": body,
                       "table": table, "columns": cols}}


async def _approval(state: AgentState) -> AgentState:
    # Resume value is a bool (legacy) or {"approved": bool, "schema": {...edited columns...}}.
    decision = interrupt({"stage": StageType.SCHEMA_PREVIEW.value, "output": state.get("output")})
    approved = decision if isinstance(decision, bool) else bool((decision or {}).get("approved"))
    if not approved:
        return {**state, "approved": False, "current_stage": StageType.DONE.value,
                "output": {**(state.get("output") or {}), "message": "Table creation cancelled.", "cancelled": True}}

    edited = (decision or {}).get("schema") if isinstance(decision, dict) else None
    if edited and edited.get("columns"):
        engine = state.get("engine", "sqlite")
        try:
            sql = _build_create_sql(edited.get("tableName"), edited["columns"])  # table renamable here
        except ValueError as e:
            return {**state, "approved": False, "current_stage": StageType.DONE.value,
                    "output": {"type": OUTPUT_ERROR, "message": f"Invalid schema edit: {e}"}}
        t1 = tier1_static(sql, engine)
        if not t1.ok or t1.kind != "DDL":
            return {**state, "approved": False, "current_stage": StageType.DONE.value,
                    "output": {"type": OUTPUT_ERROR, "message": f"Edited schema produced invalid SQL: {t1.error or t1.kind}"}}
        return {**state, "approved": True, "sql": sql, "current_stage": StageType.EXECUTION.value}

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


def _route_after_approval(state: AgentState) -> str:
    # Cancelled or an invalid edit (approved=False) → skip execution, keep the message.
    return "EXECUTION" if state.get("approved") else StageType.DONE.value


async def _done(state: AgentState) -> AgentState:
    return {**state, "current_stage": StageType.DONE.value}


class CreateTableWorkflow:
    def __init__(self):
        self._graph = None

    async def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node("SCHEMA_PREVIEW", _schema_preview)
            g.add_node("APPROVAL", _approval)
            g.add_node("EXECUTION", _execution)
            g.add_node(StageType.DONE.value, _done)
            g.set_entry_point("SCHEMA_PREVIEW")
            g.add_conditional_edges("SCHEMA_PREVIEW", _route_after_preview,
                                    {"APPROVAL": "APPROVAL", StageType.DONE.value: StageType.DONE.value})
            g.add_conditional_edges("APPROVAL", _route_after_approval,
                                    {"EXECUTION": "EXECUTION", StageType.DONE.value: StageType.DONE.value})
            g.add_edge("EXECUTION", StageType.DONE.value)
            g.add_edge(StageType.DONE.value, END)
            self._graph = g.compile(checkpointer=await get_async_checkpointer())
        return self._graph

    def _cfg(self, session_id: str) -> RunnableConfig:
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
        state = cast(AgentState, dict(snap.values) if snap and snap.values else {})
        return state, bool(getattr(snap, "next", None))
