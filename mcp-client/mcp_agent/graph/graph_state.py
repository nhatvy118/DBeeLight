"""LangGraph state definition for per-agent workflows."""

from typing import TypedDict, Optional, Any, Dict, NotRequired


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

    # Project / user scoping (optional — None for non-project sessions)
    # When set, downstream tools must enforce that resources accessed belong to this project.
    project_id: Optional[str]
    user_id: Optional[str]
    allowed_db_uri: Optional[str]

    # Intent parsing
    intent: Dict[str, Any]
    execution_plan: Dict[str, Any]
    detected_language: str
    # Set by ReadOnlyWorkflow when the orchestrator passes top-level intent (e.g. nl_query).
    orchestrator_intent: NotRequired[Optional[Dict[str, Any]]]

    # Database-specific state
    # table_schema  — {"tables": [...targeted for this query...], "all_tables": [...all physical...]}
    #                 "tables"     set by schema_discovery (refined from intent["tables"])
    #                 "all_tables" populated by schema_discovery from list_tables output
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


def create_initial_state(
    session_id: str,
    user_message: str,
    agent_type: str,
    *,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    allowed_db_uri: Optional[str] = None,
) -> AgentState:
    """Create initial state for a new session with specific agent type.

    Args:
        session_id: Unique session identifier
        user_message: User's input message
        agent_type: Which agent is handling this ("database", "excel", "chart")
        project_id: Optional project UUID — when set, scopes downstream DB access to this project
        user_id: Optional user identifier (for audit / future RLS)
        allowed_db_uri: Optional pre-resolved DB URI for the project, avoids re-querying database_agent
    """
    return {
        "session_id": session_id,
        "current_stage": "START",
        "agent_type": agent_type,
        "user_message": user_message,
        "project_id": project_id,
        "user_id": user_id,
        "allowed_db_uri": allowed_db_uri,
        "intent": {},
        "execution_plan": {},
        "detected_language": "en",

        # Database
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
