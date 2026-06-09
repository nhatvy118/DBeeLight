from __future__ import annotations

import logging
from urllib.parse import quote

from app.agent.pool import get_connection_pool
from app.config import get_settings
from app.features.projects import repository as repo

logger = logging.getLogger("projects")
_PLACEHOLDER = "placeholder://not-configured"


def is_configured(db_url: str | None) -> bool:
    return bool(db_url) and not db_url.startswith(_PLACEHOLDER)


async def connect_postgres(
    project_id: str, user_id: str, host: str, port: int, database: str, username: str, password: str
) -> tuple[bool, str]:
    """Build the DSN, probe SELECT 1 (via the in-process pool), then save db_url.

    SECURITY TODO: encrypt-at-rest the DSN with a password before saving projects.db_url.
    """
    dsn = f"postgresql://{quote(username)}:{quote(password)}@{host}:{port}/{database}"
    pool = get_connection_pool()
    try:
        await pool.probe(dsn)
    except Exception as e:  # noqa: BLE001
        return False, f"Could not connect: {e}"
    await repo.set_db_url(project_id, user_id, dsn)
    await pool.invalidate_project(project_id)  # force recreating the adapter with the new db_url
    return True, "postgresql"


async def connect_sqlite(project_id: str, user_id: str) -> tuple[bool, str]:
    """Provision a new SQLite file under DATA_ROOT/databases for the project."""
    s = get_settings()
    path = str((s.databases_dir / f"{project_id}.sqlite").resolve())
    db_url = f"sqlite:///{path}"
    pool = get_connection_pool()
    try:
        await pool.probe(db_url)  # create file + SELECT 1
    except Exception as e:  # noqa: BLE001
        return False, f"Could not create SQLite: {e}"
    await repo.set_db_url(project_id, user_id, db_url)
    await pool.invalidate_project(project_id)
    return True, "sqlite"


async def resolve_db_url(project_id: str, user_id: str) -> str | None:
    """Get the project db_url (after ownership check). Used by chat — server-side only."""
    project = await repo.get_project(project_id, user_id)
    if not project:
        return None
    db_url = project.get("db_url")
    return db_url if is_configured(db_url) else None
