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
    """Get the project db_url (after OWNERSHIP check). Used where only the owner may act
    (e.g. importing a file into the project DB)."""
    project = await repo.get_project(project_id, user_id)
    if not project:
        return None
    db_url = project.get("db_url")
    return db_url if is_configured(db_url) else None


async def resolve_db_url_for_access(project_id: str, user_id: str) -> str | None:
    """db_url if the user can ACCESS the project — owns it OR it's shared with them. Read access;
    WRITE is gated separately (viewers are blocked from mutations by role). Used by chat."""
    project = await repo.get_accessible_project(project_id, user_id)
    if not project:
        return None
    db_url = project.get("db_url")
    return db_url if is_configured(db_url) else None


class ProjectError(Exception):
    pass


async def share_project(project_id: str, owner_id: str, email: str) -> dict:
    """Owner shares their project (its DATA) with an existing user by email (read-only)."""
    if not await repo.get_project(project_id, owner_id):
        raise ProjectError("Project not found or not yours")
    from app.features.auth import repository as auth_repo
    target = await auth_repo.get_user_by_email((email or "").strip())
    if not target:
        raise ProjectError("No account with that email yet — invite them first (admin → People).")
    if target["google_sub"] == owner_id:
        raise ProjectError("You already own this project")
    await repo.add_share(project_id, target["google_sub"], owner_id)
    return {
        "user_id": target["google_sub"], "name": target.get("name"),
        "email": target.get("email"), "role": target.get("role"),
    }


async def list_project_shares(project_id: str, owner_id: str) -> list[dict]:
    if not await repo.get_project(project_id, owner_id):
        raise ProjectError("Project not found or not yours")
    return await repo.list_shares(project_id)


async def unshare_project(project_id: str, owner_id: str, viewer_id: str) -> bool:
    if not await repo.get_project(project_id, owner_id):
        raise ProjectError("Project not found or not yours")
    return await repo.remove_share(project_id, viewer_id)


async def list_shared_with(user_id: str) -> list[dict]:
    """Projects shared WITH this user (viewer home)."""
    return await repo.list_shared_with(user_id)
