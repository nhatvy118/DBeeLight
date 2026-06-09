from __future__ import annotations

from pydantic import BaseModel


class FileOut(BaseModel):
    id: str
    filename: str
    table_name: str | None = None
    imported: bool = False
