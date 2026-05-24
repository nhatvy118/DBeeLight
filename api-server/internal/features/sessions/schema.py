from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class NewSessionRequest(BaseModel):
    name: Optional[str] = None
    project_id: Optional[str] = None
