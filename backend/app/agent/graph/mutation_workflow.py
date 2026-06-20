"""Mutation workflow (LangGraph) — INSERT/UPDATE/DELETE/ALTER/DROP with APPROVAL.

Unlike the skeleton: the pending SQL lives in the **server-side checkpoint**; approve is just a
boolean resume (the client does NOT send SQL) → closes the SQL-injection hole.

Flow: INTENT → SCHEMA_DISCOVERY → SQL_PREVIEW → SQL_APPROVAL(interrupt) → EXECUTION → DONE
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
from app.agent.graph.schema_context import enrich_schema_text
from app.agent.graph.sql_verification import verify_for_mutation
from app.agent.graph.state import (
    OUTPUT_ERROR,
    OUTPUT_EXECUTION,
    OUTPUT_SQL_STATEMENT,
    AgentState,
    StageType,
    create_initial_state,
)
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.mutation")


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    return re.sub(r"\n?```$", "", t).strip()


async def _intent_parse(state: AgentState) -> AgentState:
    client = get_llm()
    resp = await client.chat.completions.create(
        model=get_settings().llm_model,
        messages=[
            {"role": "system", "content": (
                "Analyze the DB request, return JSON: operation (INSERT/UPDATE/DELETE/ALTER/DROP), "
                "tables (list of table names), resolved_query (rewrite the request in full)."
            )},
            {"role": "user", "content": state.get("user_message", "")},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        intent = json.loads(resp.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001
        intent = {}
    intent.setdefault("operation", "INSERT")
    intent.setdefault("tables", [])
    intent.setdefault("resolved_query", state.get("user_message", ""))
    return {**state, "intent": intent, "current_stage": StageType.SCHEMA_DISCOVERY.value}


async def _schema_discovery(state: AgentState) -> AgentState:
    intent = state.get("intent") or {}
    op = str(intent.get("operation", "")).upper()
    tables = [str(t).strip() for t in (intent.get("tables") or []) if str(t).strip()]
    all_tables = await dbtools.list_tables()
    lower = {t.lower() for t in all_tables}

    matched: list[str] = []
    missing: list[str] = []
    for t in tables:
        if op == "CREATE":
            continue
        if t.lower() in lower:
            matched.append(t)
        else:
            missing.append(t)

    if missing:
        avail = ", ".join(f"`{t}`" for t in all_tables[:40]) or "(none)"
        return {
            **state,
            "schema_discovery_failed": True,
            "error": f"Tables not found: {', '.join(missing)}",
            "output": {"type": OUTPUT_ERROR,
                       "message": f"**Tables not found:** {', '.join(missing)}\n\n**Available:** {avail}"},
        }
    schema_text = await enrich_schema_text(matched)  # live structure + semantic descriptions
    return {**state, "schema_discovery_failed": False,
            "table_schema": {"schema_text": schema_text, "all_tables": all_tables}}


async def _sql_preview(state: AgentState) -> AgentState:
    intent = state.get("intent") or {}
    op = str(intent.get("operation", "INSERT")).upper()
    engine = state.get("engine", "sqlite")
    schema = (state.get("table_schema", {}) or {}).get("schema_text") or ""
    client = get_llm()

    msgs = [
        {"role": "system", "content": (
            f"Generate EXACTLY ONE {op} SQL statement ({engine}) for the request. Return SQL only.\nSchema:\n{schema}"
        )},
        {"role": "user", "content": intent.get("resolved_query", state.get("user_message", ""))},
    ]
    sql = ""
    last_err = ""
    kind = "DML"  # DQL | DML | DDL — surfaced to the FE so it knows this needs approval
    for attempt in range(3):
        resp = await client.chat.completions.create(model=get_settings().llm_model, messages=msgs, temperature=0)
        sql = _strip_fences(resp.choices[0].message.content or "")
        ok, err, kind = await verify_for_mutation(sql, engine)
        if ok:
            break
        last_err = err
        msgs += [
            {"role": "assistant", "content": sql},
            {"role": "system", "content": f"SQL failed verify/EXPLAIN. Fix it, return SQL only.\nError: {err}"},
        ]
    else:
        return {**state, "sql": None, "error": last_err,
                "output": {"type": OUTPUT_ERROR, "message": f"Could not generate valid SQL.\n{last_err}"}}

    preview = await _preview(op, sql)
    body = f"```sql\n{sql}\n```\n\n{preview}\n\n_Click Execute to run._"
    return {
        **state, "sql": sql, "current_stage": StageType.SQL_PREVIEW.value,
        "output": {"type": OUTPUT_SQL_STATEMENT, "executed": False, "sql": sql,
                   "message": body, "sql_kind": kind},
    }


async def _preview(op: str, sql: str) -> str:
    if op not in ("UPDATE", "DELETE"):
        return "_See the SQL above._"
    where = ""
    wm = re.search(r"\bwhere\b(.*)$", sql, re.IGNORECASE | re.DOTALL)
    if wm:
        where = " WHERE " + wm.group(1).strip().rstrip(";")
    tm = re.search(r"(?:from|update)\s+[\"`]?([A-Za-z0-9_]+)", sql, re.IGNORECASE)
    if not tm:
        return "_Could not infer a table to preview._"
    try:
        res = await dbtools.run(f'SELECT * FROM "{tm.group(1)}"{where} LIMIT 50')
    except Exception as e:  # noqa: BLE001
        return f"_Preview error: {e}_"
    return f"**Rows that would be affected (preview):**\n\n{dbtools.md_table(res)}"


async def _sql_approval(state: AgentState) -> AgentState:
    # SQL lives in state (server-side checkpoint); the client only sends a bool decision.
    ok = interrupt({"stage": StageType.SQL_PREVIEW.value, "output": state.get("output")})
    if not ok:
        return {**state, "approved": False,
                "output": {**(state.get("output") or {}), "message": "SQL execution cancelled.", "cancelled": True}}
    return {**state, "approved": True, "current_stage": StageType.EXECUTION.value}


async def _sql_execution(state: AgentState) -> AgentState:
    if not state.get("approved"):
        return {**state, "output": {"type": "execution_skipped", "message": "Cancelled."}}
    sql = state.get("sql") or ""
    try:
        res = await dbtools.run(sql)
        msg = f"Executed successfully. ({res.rowcount} rows affected)"
        out = {"type": OUTPUT_EXECUTION, "sql": sql, "message": msg}
    except Exception as e:  # noqa: BLE001
        out = {"type": OUTPUT_ERROR, "sql": sql, "message": f"Error running SQL: {e}"}
    return {**state, "current_stage": StageType.DONE.value, "output": out}


async def _done(state: AgentState) -> AgentState:
    return {**state, "current_stage": StageType.DONE.value}


def _route_after_schema(state: AgentState) -> str:
    if state.get("schema_discovery_failed") or (state.get("output") or {}).get("type") == OUTPUT_ERROR:
        return StageType.DONE.value
    return "SQL_PREVIEW"


def _route_after_preview(state: AgentState) -> str:
    if (state.get("output") or {}).get("type") == OUTPUT_ERROR:
        return StageType.DONE.value
    return "SQL_APPROVAL"


class MutationWorkflow:
    def __init__(self):
        self._graph = None

    async def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node("INTENT", _intent_parse)
            g.add_node("SCHEMA_DISCOVERY", _schema_discovery)
            g.add_node("SQL_PREVIEW", _sql_preview)
            g.add_node("SQL_APPROVAL", _sql_approval)
            g.add_node("EXECUTION", _sql_execution)
            g.add_node(StageType.DONE.value, _done)
            g.set_entry_point("INTENT")
            g.add_edge("INTENT", "SCHEMA_DISCOVERY")
            g.add_conditional_edges("SCHEMA_DISCOVERY", _route_after_schema,
                                    {"SQL_PREVIEW": "SQL_PREVIEW", StageType.DONE.value: StageType.DONE.value})
            g.add_conditional_edges("SQL_PREVIEW", _route_after_preview,
                                    {"SQL_APPROVAL": "SQL_APPROVAL", StageType.DONE.value: StageType.DONE.value})
            g.add_edge("SQL_APPROVAL", "EXECUTION")
            g.add_edge("EXECUTION", StageType.DONE.value)
            g.add_edge(StageType.DONE.value, END)
            self._graph = g.compile(checkpointer=await get_async_checkpointer())
        return self._graph

    def _cfg(self, session_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": f"{session_id}:mutation"}}

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
        pending = bool(getattr(snap, "next", None))  # a node is waiting (interrupt) → needs approval
        return state, pending
