from __future__ import annotations

import logging
from pathlib import Path

from app.agent.pool import get_connection_pool
from app.config import get_settings
from app.features.metadata import repository as metadata_repo
from app.features.projects import repository as repo

logger = logging.getLogger("projects")
_PLACEHOLDER = "placeholder://not-configured"


def is_configured(db_url: str | None) -> bool:
    """True if the project/user has a real db_url (not the unconfigured placeholder)."""
    return bool(db_url) and not db_url.startswith(_PLACEHOLDER)


async def create_project(user_id: str, name: str, description: str = "") -> dict:
    """Create a project then auto-provision a SQLite db for it, so that it's ready-to-use in
    the chat feature.
    """
    logger.info("→ create_project(user_id=%r name=%r description=%r)", user_id, name, description)
    project = await repo.create_project(user_id, name, description)

    # auto-provision a SQLite file under DATA_ROOT/databases named after the project id
    project_id = project["id"]
    s = get_settings()
    path = str((s.databases_dir / f"{project_id}.sqlite").resolve())
    db_url = f"sqlite:///{path}"

    # opening the connection creates the .sqlite file on disk (and validates it)
    pool = get_connection_pool()
    try:
        await pool.probe(db_url)
    except Exception as e: 
        logger.warning("create_project: sqlite provisioning failed: %s", e)
        return project

    await repo.set_db_url(project_id, user_id, db_url)
    return project


async def delete_project(project_id: str, user_id: str) -> dict | None:
    """Delete the project row, release its pooled connection, and remove the
    provisioned SQLite file (and its WAL/SHM siblings) from DATA_ROOT/databases.
    """
    logger.info("→ delete_project(project_id=%r user_id=%r)", project_id, user_id)
    deleted = await repo.delete_project(project_id, user_id)
    if not deleted:
        return None
    # drop any cached adapter so the file isn't held open while we unlink it
    await get_connection_pool().invalidate(project_id)
    _delete_sqlite_file(deleted.get("db_url") or "")
    await metadata_repo.delete_for_scope("project", project_id)  # drop the project's data dictionary
    return deleted


def _delete_sqlite_file(db_url: str) -> None:
    """Remove a provisioned SQLite file, but only if it lives under databases_dir."""
    if not db_url.startswith("sqlite:///"):
        return  # nothing to delete (placeholder, postgres, etc.)
    databases_dir = get_settings().databases_dir.resolve()
    try:
        target = Path(db_url[len("sqlite:///"):]).resolve()
        if databases_dir not in target.parents:
            logger.warning("delete_project: refusing to delete out-of-tree file %s", target)
            return
        for p in (target, target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
            if p.exists():
                p.unlink()
                logger.info("delete_project: removed %s", p)
    except Exception as e:  # noqa: BLE001
        logger.warning("delete_project: failed to remove sqlite file: %s", e)


async def resolve_db_url(project_id: str, user_id: str) -> str | None:
    """Get the project db_url (after ownership check). Used by chat — server-side only."""
    project = await repo.get_project(project_id, user_id)
    if not project:
        return None
    db_url = project.get("db_url")
    return db_url if is_configured(db_url) else None
