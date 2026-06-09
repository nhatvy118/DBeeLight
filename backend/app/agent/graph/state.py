"""Shared state + stages for the LangGraph workflows."""
from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class StageType(str, Enum):
    INTENT = "INTENT"
    SCHEMA_DISCOVERY = "SCHEMA_DISCOVERY"
    SQL_PREVIEW = "SQL_PREVIEW"
    SCHEMA_PREVIEW = "SCHEMA_PREVIEW"
    SQL_APPROVAL = "SQL_APPROVAL"
    EXECUTION = "EXECUTION"
    DONE = "DONE"
    ERROR = "ERROR"


# Output type for the frontend
OUTPUT_SQL_STATEMENT = "sql_statement"
OUTPUT_SCHEMA_PREVIEW = "schema_preview"
OUTPUT_EXECUTION = "execution_complete"
OUTPUT_ERROR = "error"
OUTPUT_AGENT = "agent_response"


class AgentState(TypedDict, total=False):
    session_id: str
    user_message: str
    engine: str                 # sqlite | postgresql
    intent: dict[str, Any]
    table_schema: dict[str, Any]
    sql: str | None
    approved: bool
    current_stage: str
    error: str | None
    output: dict[str, Any]
    query_result: Any
    schema_discovery_failed: bool


def create_initial_state(session_id: str, user_message: str, engine: str) -> AgentState:
    return {
        "session_id": session_id,
        "user_message": user_message,
        "engine": engine,
        "intent": {},
        "table_schema": {},
        "sql": None,
        "approved": False,
        "current_stage": StageType.INTENT.value,
        "error": None,
        "output": {},
    }
