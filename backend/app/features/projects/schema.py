from __future__ import annotations

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str = ""
    has_db: bool = False


class ConnectPostgres(BaseModel):
    host: str
    port: int = 5432
    database: str
    username: str
    password: str


class ConnectResult(BaseModel):
    status: str
    engine: str | None = None
    detail: str | None = None
