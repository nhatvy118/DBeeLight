"""ReadOnly workflow (LangGraph) — controlled SELECT.

No interrupt (read-only is safe) → runs straight through. Enforces require_dql_only: even if
the LLM accidentally emits a write, it is rejected (safer than a free tool loop).

Flow: SCHEMA_DISCOVERY → QUERY_EXECUTION → DONE
"""
from __future__ import annotations

import logging
import re
from typing import Any, cast

from langgraph.graph import END, StateGraph

from app.agent.graph import dbtools
from app.agent.graph.schema_context import enrich_schema_text
from app.agent.graph.sql_verification import require_dql_only, tier2_explain
from app.agent.graph.state import OUTPUT_ERROR, AgentState, StageType, create_initial_state
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.readonly")


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    return re.sub(r"\n?```$", "", t).strip()


async def _schema_discovery(state: AgentState) -> AgentState:
    tables = await dbtools.list_tables()
    schema_text = await enrich_schema_text(tables)  # live structure + semantic descriptions
    return {**state, "table_schema": {"schema_text": schema_text, "all_tables": tables}}


async def _query_execution(state: AgentState) -> AgentState:
    engine = state.get("engine", "sqlite")
    schema = (state.get("table_schema", {}) or {}).get("schema_text") or ""
    client = get_llm()
    msgs: list[dict] = [
        {"role": "system", "content": (
            f"Generate EXACTLY ONE SELECT statement ({engine}) to answer the question. Return SQL only, no explanation.\n"
            f"Schema:\n{schema}"
        )},
        {"role": "user", "content": state.get("user_message", "")},
    ]
    sql = ""
    last_err = ""
    for _ in range(3):
        resp = await client.chat.completions.create(model=get_settings().llm_model, messages=cast(Any, msgs), temperature=0)
        sql = _strip_fences(resp.choices[0].message.content or "")
        dql_err = require_dql_only(sql, engine)
        if dql_err:
            last_err = dql_err
            msgs += [{"role": "assistant", "content": sql},
                     {"role": "system", "content": f"SELECT only. Fix it.\nError: {dql_err}"}]
            continue
        ok, err = await tier2_explain(sql)
        if ok:
            break
        last_err = err
        msgs += [{"role": "assistant", "content": sql},
                 {"role": "system", "content": f"SQL failed EXPLAIN. Fix it.\nError: {err}"}]
    else:
        return {**state, "current_stage": StageType.DONE.value, "sql": sql,
                "output": {"type": OUTPUT_ERROR, "message": f"Could not generate a valid SELECT.\n{last_err}"}}

    try:
        res = await dbtools.run(sql)
    except Exception as e:  # noqa: BLE001
        return {**state, "current_stage": StageType.DONE.value,
                "output": {"type": OUTPUT_ERROR, "message": f"Error running SQL: {e}"}}
    body = f"```sql\n{sql}\n```\n\n{dbtools.md_table(res)}"
    return {**state, "sql": sql, "current_stage": StageType.DONE.value,
            "query_result": res.to_dict(),
            "output": {"type": "agent_response", "sql": sql, "message": body}}


class ReadOnlyWorkflow:
    def __init__(self):
        self._graph = None

    def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node("SCHEMA_DISCOVERY", _schema_discovery)
            g.add_node("QUERY_EXECUTION", _query_execution)
            g.set_entry_point("SCHEMA_DISCOVERY")
            g.add_edge("SCHEMA_DISCOVERY", "QUERY_EXECUTION")
            g.add_edge("QUERY_EXECUTION", END)
            self._graph = g.compile()  # no checkpointer needed (no interrupt)
        return self._graph

    async def run(self, session_id: str, user_message: str, engine: str) -> AgentState:
        graph = self._compiled()
        result = await graph.ainvoke(create_initial_state(session_id, user_message, engine))
        return cast(AgentState, dict(result))
