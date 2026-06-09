from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None        # null → a new session is created
    project_id: str | None = None        # used only when creating a session
    active_file_ids: list[str] | None = None


class ResumeRequest(BaseModel):
    session_id: str
    approved: bool = True
    # SQL is not accepted from the client — it lives in the server-side checkpoint (anti-injection).


class ChatResponse(BaseModel):
    success: bool = True
    response: str
    session_id: str | None = None
    route: str | None = None
    requires_approval: bool = False
    pending_workflow_resume: bool = False
    needs_clarification: bool = False
    tool_events: list[dict] = []
