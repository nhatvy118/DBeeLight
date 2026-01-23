from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class NewSessionRequest(BaseModel):
    name: Optional[str] = None


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

