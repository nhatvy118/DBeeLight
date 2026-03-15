"""LangGraph state definitions and types for per-agent workflows."""

from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Session status enum."""
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    DONE = "DONE"
    FAILED = "FAILED"


class StageType(str, Enum):
    """Stage types - can be extended per agent."""
    # Common stages
    START = "START"
    INTENT_PARSE = "INTENT_PARSE"
    DONE = "DONE"
    ERROR = "ERROR"

    # Database agent stages
    SCHEMA_DISCOVERY = "SCHEMA_DISCOVERY"
    SQL_GENERATION = "SQL_GENERATION"
    SQL_PREVIEW = "SQL_PREVIEW"
    SQL_EXECUTION = "SQL_EXECUTION"

    # Excel agent stages
    FILE_LOAD = "FILE_LOAD"
    DATA_ANALYZE = "DATA_ANALYZE"
    DATA_TRANSFORM = "DATA_TRANSFORM"
    EXPORT = "EXPORT"
    CHART_GENERATE = "CHART_GENERATE"
    IMPORT_PREPARE = "IMPORT_PREPARE"
    IMPORT_EXECUTE = "IMPORT_EXECUTE"

    # Email agent stages (example)
    EMAIL_CONNECT = "EMAIL_CONNECT"
    EMAIL_SEND = "EMAIL_SEND"
    EMAIL_LIST = "EMAIL_LIST"


class AgentWorkflowConfig(BaseModel):
    """Configuration for an agent's workflow."""
    agent_id: str
    stages: List[StageType]
    # Map stage to next stage
    transitions: Dict[str, Optional[str]] = Field(default_factory=dict)
    # Stages that require user approval
    wait_stages: List[str] = Field(default_factory=list)


# Predefined workflow configs for each agent type
DATABASE_WORKFLOW = AgentWorkflowConfig(
    agent_id="database",
    stages=[
        StageType.INTENT_PARSE,
        StageType.SCHEMA_DISCOVERY,
        StageType.SQL_GENERATION,
        StageType.SQL_PREVIEW,
        StageType.SQL_EXECUTION,
    ],
    transitions={
        StageType.INTENT_PARSE.value: StageType.SCHEMA_DISCOVERY.value,
        StageType.SCHEMA_DISCOVERY.value: StageType.SQL_GENERATION.value,
        StageType.SQL_GENERATION.value: StageType.SQL_PREVIEW.value,
        StageType.SQL_PREVIEW.value: StageType.SQL_EXECUTION.value,
        StageType.SQL_EXECUTION.value: StageType.DONE.value,
    },
    wait_stages=[StageType.SQL_PREVIEW.value],
)

EXCEL_WORKFLOW = AgentWorkflowConfig(
    agent_id="excel",
    stages=[
        StageType.INTENT_PARSE,
        StageType.FILE_LOAD,
        StageType.DATA_ANALYZE,
        StageType.DATA_TRANSFORM,
        StageType.CHART_GENERATE,
        StageType.EXPORT,
    ],
    transitions={
        StageType.INTENT_PARSE.value: StageType.FILE_LOAD.value,
        StageType.FILE_LOAD.value: StageType.DATA_ANALYZE.value,
        StageType.DATA_ANALYZE.value: StageType.DATA_TRANSFORM.value,
        StageType.DATA_TRANSFORM.value: StageType.CHART_GENERATE.value,
        StageType.CHART_GENERATE.value: StageType.EXPORT.value,
        StageType.EXPORT.value: StageType.DONE.value,
    },
    wait_stages=[],
)

# Registry of agent workflows
AGENT_WORKFLOWS: Dict[str, AgentWorkflowConfig] = {
    "database": DATABASE_WORKFLOW,
    "excel": EXCEL_WORKFLOW,
}


class AgentContext(BaseModel):
    """Context passed through the workflow."""
    # User input
    user_message: str = ""

    # Intent
    intent: Dict[str, Any] = Field(default_factory=dict)
    detected_language: str = "en"

    # Database context
    tables: List[str] = Field(default_factory=list)
    selected_table: Optional[str] = None
    table_schema: Dict[str, Any] = Field(default_factory=dict)
    sql: Optional[str] = None

    # Execution context
    query_result: Optional[Any] = None
    affected_rows: int = 0

    # Excel context
    file_path: Optional[str] = None
    sheet_name: Optional[str] = None
    data: Optional[List[Dict]] = None
    export_path: Optional[str] = None

    # Chart context
    chart_type: Optional[str] = None
    chart_data: Optional[Dict] = None

    # Email context (example)
    email_to: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None

    # State
    wait_user: bool = False
    approved: bool = False
    error: Optional[str] = None
    retry_count: int = 0


class StageResult(BaseModel):
    """Result from a stage execution."""
    next_stage: Optional[str] = None
    wait_user: bool = False
    updates: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
