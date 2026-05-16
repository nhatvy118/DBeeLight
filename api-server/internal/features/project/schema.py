from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    db_url: Optional[str] = None
