from __future__ import annotations

from pydantic import BaseModel


class SessionCreate(BaseModel):
    project_id: str
    title: str = "New chat"


class SessionOut(BaseModel):
    id: str
    project_id: str
    title: str


class MessageOut(BaseModel):
    role: str
    content: str
    tool_events: list[dict] = []
