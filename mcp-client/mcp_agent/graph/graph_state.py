"""LangGraph state definition for per-agent workflows."""

from typing import TypedDict, Optional, Any, Dict


class AgentState(TypedDict):
    """State passed through the LangGraph workflow for a specific agent.

    Each agent has its own workflow with different stages.
    """
    # Session info
    session_id: str
    current_stage: str

    # Agent identification
    agent_type: str  # "database", "excel", etc.

    # User input
    user_message: str

    # Intent parsing
    intent: Dict[str, Any]
    execution_plan: Dict[str, Any]
    detected_language: str

    # Database-specific state
    tables: list
    selected_table: Optional[str]
    table_schema: Dict[str, Any]
    sql: Optional[str]
    query_result: Optional[Any]
    affected_rows: int

    # Excel-specific state
    file_path: Optional[str]
    sheet_name: Optional[str]
    data: Optional[list]
    export_path: Optional[str]

    # Chart-specific state
    chart_type: Optional[str]
    chart_data: Optional[Dict[str, Any]]

    # Flow control
    wait_user: bool
    approved: bool
    error: Optional[str]
    retry_count: int

    # Output for UI
    output: Dict[str, Any]


def create_initial_state(session_id: str, user_message: str, agent_type: str) -> AgentState:
    """Create initial state for a new session with specific agent type.

    Args:
        session_id: Unique session identifier
        user_message: User's input message
        agent_type: Which agent is handling this ("database", "excel", etc.)
    """
    return {
        "session_id": session_id,
        "current_stage": "START",
        "agent_type": agent_type,
        "user_message": user_message,
        "intent": {},
        "execution_plan": {},
        "detected_language": "en",

        # Database
        "tables": [],
        "selected_table": None,
        "table_schema": {},
        "sql": None,
        "query_result": None,
        "affected_rows": 0,

        # Excel
        "file_path": None,
        "sheet_name": None,
        "data": None,
        "export_path": None,

        # Chart
        "chart_type": None,
        "chart_data": None,

        # Email
        "email_to": None,
        "email_subject": None,
        "email_body": None,

        # Flow
        "wait_user": False,
        "approved": False,
        "error": None,
        "retry_count": 0,

        # Output
        "output": {},
    }
