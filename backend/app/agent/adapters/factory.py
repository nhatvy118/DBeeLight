"""Create an adapter from a db_url (project.db_url or a SQLite file path)."""
from __future__ import annotations

from urllib.parse import urlparse

from app.agent.adapters.base import DatabaseAdapter
from app.agent.adapters.postgres import PostgresAdapter
from app.agent.adapters.sqlite import SQLiteAdapter


def _to_sqlalchemy_url(db_url: str) -> tuple[str, str]:
    """Return (sqlalchemy_url, engine_name). Accepts:
    - sqlite:///path or a plain file path (*.sqlite/.db)
    - postgresql://... / postgres://...
    """
    raw = db_url.strip()
    scheme = urlparse(raw).scheme.lower()

    if scheme in ("postgresql", "postgres"):
        # force the asyncpg driver
        tail = raw.split("://", 1)[1]
        return f"postgresql+asyncpg://{tail}", "postgresql"

    if scheme == "sqlite":
        path = raw[len("sqlite:///"):] if raw.startswith("sqlite:///") else urlparse(raw).path
        return f"sqlite+aiosqlite:///{path}", "sqlite"

    # no scheme → treat as a SQLite file path
    return f"sqlite+aiosqlite:///{raw}", "sqlite"


def make_adapter(db_url: str, allowed_tables: frozenset[str] | None = None) -> DatabaseAdapter:
    sa_url, engine = _to_sqlalchemy_url(db_url)
    if engine == "postgresql":
        return PostgresAdapter(sa_url, allowed_tables=allowed_tables)
    return SQLiteAdapter(sa_url, allowed_tables=allowed_tables)
