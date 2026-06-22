"""Shared state + stages for the LangGraph workflows."""
from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class StageType(str, Enum):
    """Single source of truth for graph node names (and the interrupt 'stage' marker sent to the
    FE for SQL_PREVIEW / SCHEMA_PREVIEW). Every workflow node is wired by one of these, never a
    raw string, so add_node and add_edge can never drift."""
    SCHEMA_DISCOVERY = "SCHEMA_DISCOVERY"
    QUERY_EXECUTION = "QUERY_EXECUTION"
    SQL_PREVIEW = "SQL_PREVIEW"
    SCHEMA_PREVIEW = "SCHEMA_PREVIEW"
    APPROVAL = "APPROVAL"
    EXECUTION = "EXECUTION"
    DONE = "DONE"


# Output type for the frontend
OUTPUT_SQL_STATEMENT = "sql_statement"
OUTPUT_SCHEMA_PREVIEW = "schema_preview"
OUTPUT_EXECUTION = "execution_complete"
OUTPUT_QUERY_RESULT = "query_result"   # read-only SELECT result: structured {columns, rows} for the FE
OUTPUT_ERROR = "error"


class AgentState(TypedDict, total=False):
    user_message: str
    engine: str                 # sqlite | postgresql
    schema_text: str            # enriched schema text, set by SCHEMA_DISCOVERY for the SQL generator
    sql: str | None
    approved: bool
    action_id: str              # stable UUID for the gated action (survives interrupt via checkpoint)
    output: dict[str, Any]


def create_initial_state(user_message: str, engine: str) -> AgentState:
    return {
        "user_message": user_message,
        "engine": engine,
        "sql": None,
        "approved": False,
        "output": {},
    }
