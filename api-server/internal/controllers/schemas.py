from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    project_id: Optional[str] = None


class NewSessionRequest(BaseModel):
    name: Optional[str] = None
    project_id: Optional[str] = None


class ChatOk(BaseModel):
    success: bool = True
    response: str
    session_id: Optional[str] = None


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
    session_id: Optional[str] = None
    project_id: Optional[str] = None

