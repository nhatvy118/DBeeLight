from __future__ import annotations

from pydantic import BaseModel


class HealthOk(BaseModel):
    status: str
    agent_initialized: bool
