from __future__ import annotations

from pydantic import BaseModel


class FileOut(BaseModel):
    id: str
    filename: str
    imported: bool = False
