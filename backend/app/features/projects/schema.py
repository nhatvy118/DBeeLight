from __future__ import annotations

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ExternalConnection(BaseModel):
    """Connection form for an external Postgres database (used to test or edit a connection)."""
    host: str
    port: int = 5432
    database: str
    username: str = ""
    password: str = ""


class ExternalProjectCreate(ExternalConnection):
    """Create a project bound to an external database: a name plus the connection fields."""
    name: str
    description: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str = ""
    kind: str = "internal"
