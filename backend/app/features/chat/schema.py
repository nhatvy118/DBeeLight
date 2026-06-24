from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None        # null → server creates a "New chat" session
    project_id: str | None = None        # used only when creating a session
    active_file_ids: list[str] | None = None


class ResumeRequest(BaseModel):
    session_id: str
    approved: bool = True
    # SQL is not accepted from the client — it lives in the server-side checkpoint (anti-injection).
    # For create_table, the client MAY send the user-edited schema (structured columns); the server
    # rebuilds + re-verifies the CREATE SQL from it (never trusts a client-sent SQL string).
    edited_schema: dict | None = None


class ChatResponse(BaseModel):
    success: bool = True
    response: str
    session_id: str | None = None
    route: str | None = None
    requires_approval: bool = False
    pending_workflow_resume: bool = False
    needs_clarification: bool = False
    tool_events: list[dict] = []
