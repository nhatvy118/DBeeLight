"""ReadOnly workflow (LangGraph) — controlled SELECT.

No interrupt (read-only is safe) → runs straight through. Enforces is_read_only: even if
the LLM accidentally emits a write, it is rejected (safer than a free tool loop).

Flow: SCHEMA_DISCOVERY → QUERY_EXECUTION → DONE
"""
from __future__ import annotations

import logging
from typing import cast

from langgraph.graph import END, StateGraph

from app.agent.graph import dbtools
from app.agent.graph.nl_answer import answer_from_result
from app.agent.graph.schema_context import enrich_schema_text
from app.agent.graph.sql_gen import generate_sql
from app.agent.graph.stages import StageCb, stream_stages
from app.agent.graph.state import (
    OUTPUT_ERROR,
    OUTPUT_QUERY_RESULT,
    AgentState,
    StageType,
    create_initial_state,
)

logger = logging.getLogger("agent.graph.readonly")


async def _schema_discovery(state: AgentState) -> AgentState:
    schema_text = await enrich_schema_text(mode="read")  # lean: no write-only default/UNIQUE
    return {**state, "schema_text": schema_text}


async def _query_execution(state: AgentState) -> AgentState:
    engine = state.get("engine", "sqlite")
    schema = state.get("schema_text") or ""
    sql, err, _ = await generate_sql(state.get("user_message", ""), schema, engine, mode="read")
    if err:
        return {**state, "sql": sql,
                "output": {"type": OUTPUT_ERROR, "message": f"Could not generate a valid SELECT.\n{err}"}}

    try:
        res = await dbtools.run(sql)
    except Exception as e:  # noqa: BLE001
        return {**state, "output": {"type": OUTPUT_ERROR,
                "message": f"The query couldn’t run: {dbtools.clean_db_error(str(e))}."}}
    # Structured result: the server does NOT render the table — it ships {columns, rows} and the
    # frontend renders it. The message carries a one-sentence NL answer (so "how many…?" gets a
    # spoken "There are …", not just a table) followed by the SQL fence (the on-theme SQL card).
    result = res.to_dict()
    answer = await answer_from_result(state.get("user_message", ""), result)
    message = f"{answer}\n\n```sql\n{sql}\n```" if answer else f"```sql\n{sql}\n```"
    return {**state, "sql": sql,
            "output": {"type": OUTPUT_QUERY_RESULT, "sql": sql,
                       "message": message, "result": result}}


class ReadOnlyWorkflow:
    def __init__(self):
        self._graph = None

    def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node(StageType.SCHEMA_DISCOVERY.value, _schema_discovery)
            g.add_node(StageType.QUERY_EXECUTION.value, _query_execution)
            g.set_entry_point(StageType.SCHEMA_DISCOVERY.value)
            g.add_edge(StageType.SCHEMA_DISCOVERY.value, StageType.QUERY_EXECUTION.value)
            g.add_edge(StageType.QUERY_EXECUTION.value, END)
            self._graph = g.compile()  # no checkpointer needed (no interrupt)
        return self._graph

    async def run(
        self, session_id: str, user_message: str, engine: str, on_stage: StageCb | None = None
    ) -> AgentState:
        # session_id keeps the uniform workflow.run() signature; readonly has no checkpoint to key.
        graph = self._compiled()
        # astream emits a stage per node; the last 'values' chunk is the final state (no checkpointer).
        result = await stream_stages(graph, create_initial_state(user_message, engine), on_stage)
        return cast(AgentState, dict(result or {}))
