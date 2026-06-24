from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypeGuard, cast
from urllib.parse import quote, unquote, urlparse, parse_qs

from app.agent.llm import get_llm
from app.agent.pool import get_connection_pool
from app.config import get_settings
from app.features.metadata import repository as metadata_repo
from app.features.projects import repository as repo

logger = logging.getLogger("projects")
_PLACEHOLDER = "placeholder://not-configured"
_GENERIC_CONNECT_ERROR = (
    "Could not connect. Please double-check your host, port, database, username and password."
)


def is_configured(db_url: str | None) -> TypeGuard[str]:
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


async def get_connection_info(project_id: str, user_id: str) -> dict:
    """Decompose an external project's stored DSN back into connection fields (host/port/database/
    username/ssl) so the OWNER can review them. The password is never returned.
    Owner-only; raises ProjectError for a missing/internal/unconfigured project."""
    project = await repo.get_project(project_id, user_id)
    if not project:
        raise ProjectError("Project not found or not yours")
    if project.get("kind") != "external":
        raise ProjectError("Only external projects have a connection")
    db_url = project.get("db_url") or ""
    if not is_configured(db_url):
        raise ProjectError("This project has no connection configured yet")
    u = urlparse(db_url)
    q = parse_qs(u.query)
    # Password is intentionally NOT returned — never expose stored credentials, even to the owner.
    return {
        "host": u.hostname or "",
        "port": u.port or 5432,
        "database": (u.path or "").lstrip("/"),
        "username": unquote(u.username) if u.username else "",
        # managed Postgres often needs SSL — probe_connection appends ?ssl=require when it does.
        "ssl": "ssl" in q or "sslmode" in q,
    }


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


async def list_tables(project_id: str, user_id: str) -> list[dict]:
    """Tables in the project's database (owner-only), as [{name, columns:[...]}] — used to pick a
    target when appending an uploaded file into an existing table. Empty list if no DB configured."""
    project = await repo.get_project(project_id, user_id)
    if not project:
        raise ProjectError("Project not found or not yours")
    db_url = project.get("db_url")
    if not is_configured(db_url):
        return []
    adapter = await get_connection_pool().adapter_for(project_id, db_url)
    schema = await adapter.get_schema()
    return [{"name": t, "columns": [c.name for c in cols]} for t, cols in schema.items()]


async def _owned_adapter(project_id: str, user_id: str):
    """(adapter, schema) for a project the user OWNS, or raise ProjectError. Shared used by the
    table-description endpoints (owner-only — descriptions are an authoring action)."""
    project = await repo.get_project(project_id, user_id)
    if not project:
        raise ProjectError("Project not found or not yours")
    db_url = project.get("db_url")
    if not is_configured(db_url):
        raise ProjectError("Project has no database connected")
    adapter = await get_connection_pool().adapter_for(project_id, db_url)
    return adapter, await adapter.get_schema()


async def suggest_table_descriptions(project_id: str, user_id: str, table: str) -> dict:
    """LLM-suggested table + per-column descriptions for an imported table, from its column names
    and a few sample rows. Best-effort: on any failure returns empty strings (the user can still
    type their own). Owner-only."""
    adapter, schema = await _owned_adapter(project_id, user_id)
    if table not in schema:
        raise ProjectError(f"Table '{table}' doesn't exist in the database.")
    columns = [c.name for c in schema[table]]
    empty = {"tableDescription": "", "columns": [{"name": c, "description": ""} for c in columns]}
    try:
        res = await adapter.execute(f'SELECT * FROM "{table}" LIMIT 5')
        sample = {"columns": list(res.columns), "rows": [[_cell(v) for v in r] for r in res.rows]}
    except Exception as e:  # noqa: BLE001 — no samples is fine; suggest from names alone
        logger.warning("describe-suggest: sample read failed for %r: %s", table, e)
        sample = {"columns": columns, "rows": []}
    msgs: list[dict] = [
        {"role": "system", "content": (
            "You write a data dictionary. Given a table name, its columns, and a few sample rows, "
            "write a SHORT plain-language description for the TABLE and for EVERY column (what it "
            "holds, units or codes where obvious). Be concise and factual; do not invent meaning "
            "you cannot infer. Return JSON only: "
            '{"tableDescription": "...", "columns": [{"name": "...", "description": "..."}]}'
        )},
        {"role": "user", "content": (
            f"Table: {table}\nColumns: {', '.join(columns)}\n"
            f"Sample:\n{json.dumps(sample, ensure_ascii=False, default=str)}"
        )},
    ]
    try:
        resp = await get_llm().chat.completions.create(
            model=get_settings().llm_model, messages=cast(Any, msgs), temperature=0,
            response_format={"type": "json_object"},
        )
        spec = json.loads(resp.choices[0].message.content or "{}")
    except Exception as e:  # noqa: BLE001 — suggestion is optional; fall back to empty
        logger.warning("describe-suggest: LLM failed for %r: %s", table, e)
        return empty
    # Align the model's output back to the real column list (ignore hallucinated/missing cols).
    by_name = {str(c.get("name", "")).lower(): str(c.get("description") or "")
               for c in (spec.get("columns") or []) if isinstance(c, dict)}
    return {
        "tableDescription": str(spec.get("tableDescription") or ""),
        "columns": [{"name": c, "description": by_name.get(c.lower(), "")} for c in columns],
    }


async def save_table_descriptions(
    project_id: str, user_id: str, table: str, table_description: str, columns: list[dict]
) -> None:
    """Persist user-edited table + column descriptions to the data dictionary (owner-only). Only
    non-empty descriptions are written; the table must exist in the project DB."""
    _, schema = await _owned_adapter(project_id, user_id)
    if table not in schema:
        raise ProjectError(f"Table '{table}' doesn't exist in the database.")
    valid_cols = {c.name.lower() for c in schema[table]}
    rows: list[dict] = []
    if table_description.strip():
        rows.append({"table": table, "column": None, "description": table_description.strip()})
    for c in columns or []:
        name = str(c.get("name") or "").strip()
        desc = str(c.get("description") or "").strip()
        if name and desc and name.lower() in valid_cols:
            rows.append({"table": table, "column": name, "description": desc})
    await metadata_repo.upsert_descriptions("project", project_id, rows)


def _cell(v: object) -> object:
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


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
    project = await repo.get_project(project_id, owner_id)
    if not project:
        raise ProjectError("Project not found or not yours")
    from app.features.auth import repository as auth_repo
    target = await auth_repo.get_user_by_email((email or "").strip())
    if not target:
        raise ProjectError("No account with that email yet — invite them first (admin → People).")
    if target["google_sub"] == owner_id:
        raise ProjectError("You already own this project")
    perm = _effective_permission(permission, target.get("role"))
    await repo.add_share(project_id, target["google_sub"], owner_id, perm)

    # Notify the recipient (best-effort; a failed email must not fail the share).
    owner = await auth_repo.get_user(owner_id)
    from app import email as email_mod
    await email_mod.send_share_email(
        target.get("email") or "", (owner or {}).get("name") or "",
        project.get("name") or "", perm,
    )
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
