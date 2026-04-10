from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    project_id: Optional[str] = None


class WorkflowResumeRequest(BaseModel):
    """Resume a database LangGraph workflow paused on ``interrupt()`` (schema or SQL gate)."""

    session_id: str
    approved: bool = True
    project_id: Optional[str] = None
    user_visible_message: Optional[str] = None


class NewSessionRequest(BaseModel):
    name: Optional[str] = None
    project_id: Optional[str] = None


class ChatOk(BaseModel):
    success: bool = True
    response: str
    session_id: Optional[str] = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    tool_events: list[dict[str, Any]] = Field(default_factory=list)
    pending_workflow_resume: bool = False


class ErrorResp(BaseModel):
    success: bool = False
    error: str


class HealthOk(BaseModel):
    status: str
    agent_initialized: bool


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    db_url: Optional[str] = None


class GenerateShareLinkRequest(BaseModel):
    session_id: Optional[str] = None
    project_id: Optional[str] = None


class ExecuteSqlRequest(BaseModel):
    sql: str
    action_id: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    lang: Optional[str] = "en"  # Language for translation
    lock_only: Optional[bool] = False
    lock_state: Optional[str] = None


class ExportRequest(BaseModel):
    table_name: str
    columns: Optional[str] = "*"
    where_clause: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    format: Optional[str] = "csv"  # "csv" or "excel"


class UploadExcelOk(BaseModel):
    success: bool = True
    file: dict[str, Any]

