from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    active_file_ids: Optional[list[str]] = None  # Data sources selected in UI (file UUIDs or '__primary_db__')


class WorkflowResumeRequest(BaseModel):
    """Resume a database LangGraph workflow paused on ``interrupt()`` (schema or SQL gate)."""

    session_id: str
    approved: bool = True
    project_id: Optional[str] = None
    user_visible_message: Optional[str] = None


class ExecuteSqlRequest(BaseModel):
    sql: str
    action_id: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    lock_only: Optional[bool] = False
    lock_state: Optional[str] = None


class DbConnectRequest(BaseModel):
    host: str
    port: int = 5432
    database: str
    username: str
    password: str = ""


class DbConnectOk(BaseModel):
    success: bool
    message: str


class ChatOk(BaseModel):
    success: bool = True
    response: str
    session_id: Optional[str] = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    tool_events: list[dict[str, Any]] = Field(default_factory=list)
    pending_workflow_resume: bool = False
