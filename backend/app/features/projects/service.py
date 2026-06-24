from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from app.agent.pool import get_connection_pool
from app.config import get_settings
from app.features.metadata import repository as metadata_repo
from app.features.projects import repository as repo

logger = logging.getLogger("projects")
_PLACEHOLDER = "placeholder://not-configured"
_GENERIC_CONNECT_ERROR = (
    "Could not connect. Please double-check your host, port, database, username and password."
)


def is_configured(db_url: str | None) -> bool:
    """True if the project/user has a real db_url (not the unconfigured placeholder)."""
    return bool(db_url) and not db_url.startswith(_PLACEHOLDER)


def build_dsn(host: str, port: int | None, database: str, username: str, password: str) -> str:
    """Assemble a Postgres DSN from connection form fields (credentials are URL-encoded)."""
    return (
        f"postgresql://{quote(username or '')}:{quote(password or '')}"
        f"@{host}:{int(port or 5432)}/{database}"
    )


async def probe_connection(dsn: str) -> str:
    """Validate an external DSN; retry once with SSL (managed Postgres — Neon/Supabase/RDS — often
    requires it). Returns the DSN that worked (possibly with ?ssl=require). Raises ProjectError."""
    pool = get_connection_pool()
    try:
        await pool.probe(dsn)
        return dsn
    except Exception as e1:  # noqa: BLE001
        ssl_dsn = f"{dsn}?ssl=require"
        try:
            await pool.probe(ssl_dsn)
            return ssl_dsn
        except Exception as e2:  # noqa: BLE001
            logger.warning("probe_connection failed: plain=%r ssl=%r", e1, e2)
            raise ProjectError(_GENERIC_CONNECT_ERROR) from e2


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


async def create_external_project(user_id: str, name: str, dsn: str, description: str = "") -> dict:
    """Create a project bound to the user's OWN external database. The DSN is probed first (so a
    bad connection fails fast, before a half-configured row is created) and stored server-side as
    db_url — never auto-provisioning SQLite. Raises ProjectError if the connection fails."""
    logger.info("→ create_external_project(user_id=%r name=%r)", user_id, name)
    working = await probe_connection(dsn)
    return await repo.create_project(user_id, name, description, kind="external", db_url=working)


async def update_project_connection(project_id: str, user_id: str, dsn: str) -> None:
    """Re-point an external project at a new DSN (Edit connection). Owner-only; the new DSN is
    probed before it replaces the old one, and the pooled adapter is dropped so the next query
    opens the new database. Raises ProjectError on a missing/non-external project or a bad DSN."""
    logger.info("→ update_project_connection(project_id=%r user_id=%r)", project_id, user_id)
    project = await repo.get_project(project_id, user_id)
    if not project:
        raise ProjectError("Project not found or not yours")
    if project.get("kind") != "external":
        raise ProjectError("Only external projects have a connection to edit")
    working = await probe_connection(dsn)
    await repo.set_db_url(project_id, user_id, working)
    await get_connection_pool().invalidate(project_id)


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


def _effective_permission(requested: str, target_role: str | None) -> str:
    """EDIT is only honoured for technical recipients; viewers (and anyone else) are view-only."""
    return "edit" if (requested == "edit" and target_role == "technical") else "view"


async def share_project(project_id: str, owner_id: str, email: str, permission: str = "view") -> dict:
    """Owner shares their project (its DATA) with an existing user by email. `permission` may be
    'view' or 'edit', but 'edit' is only granted to technical recipients (viewers stay view-only)."""
    if not await repo.get_project(project_id, owner_id):
        raise ProjectError("Project not found or not yours")
    from app.features.auth import repository as auth_repo
    target = await auth_repo.get_user_by_email((email or "").strip())
    if not target:
        raise ProjectError("No account with that email yet — invite them first (admin → People).")
    if target["google_sub"] == owner_id:
        raise ProjectError("You already own this project")
    perm = _effective_permission(permission, target.get("role"))
    await repo.add_share(project_id, target["google_sub"], owner_id, perm)
    return {
        "user_id": target["google_sub"], "name": target.get("name"),
        "email": target.get("email"), "role": target.get("role"), "permission": perm,
    }


async def set_share_permission(project_id: str, owner_id: str, viewer_id: str, permission: str) -> str:
    """Change a person's access on this project. Returns the EFFECTIVE permission (viewers can
    never get 'edit')."""
    if not await repo.get_project(project_id, owner_id):
        raise ProjectError("Project not found or not yours")
    from app.features.auth import repository as auth_repo
    target = await auth_repo.get_user(viewer_id)
    perm = _effective_permission(permission, (target or {}).get("role"))
    if not await repo.set_share_permission(project_id, viewer_id, perm):
        raise ProjectError("Share not found")
    return perm


async def user_can_edit(project_id: str, user_id: str, role: str | None) -> bool:
    """Can this user WRITE (mutate/create) on this project? Owner always; a SHARED user only when
    they are technical AND the share grants 'edit'. Viewers never edit."""
    if role == "viewer":
        return False
    if await repo.get_project(project_id, user_id):   # owner
        return True
    return (await repo.get_share_permission(project_id, user_id)) == "edit"


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


async def list_shareable(project_id: str, owner_id: str) -> list[dict]:
    """Users the owner can still share this project with (pick-list in the share modal)."""
    if not await repo.get_project(project_id, owner_id):
        raise ProjectError("Project not found or not yours")
    return await repo.list_shareable_users(project_id, owner_id)
