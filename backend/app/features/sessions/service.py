"""Sessions service — read-only helpers that don't belong in the router or repository.

db_descriptor() summarizes a session's primary DB for the UI. It mirrors the
db_url resolution in chat.service._authorize, but is non-raising and NEVER exposes
the DSN (only a human label). The frontend uses this instead of guessing from
localStorage, so "does this session have a DB?" has a single source of truth: the
session's project_id (project DB) vs the user's active_db_url (external/global).
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.features.auth import repository as auth_repo
from app.features.projects import repository as proj_repo
from app.features.projects import service as proj_service

logger = logging.getLogger("sessions")


def _external_label(dsn: str) -> str | None:
    """'<database>@<host>' from a DSN — never the user/password (redacted by design)."""
    try:
        u = urlparse(dsn)
        db = (u.path or "").lstrip("/")
        host = u.hostname or "localhost"
        return f"{db}@{host}" if db else host
    except Exception:  # noqa: BLE001
        return None


def _configured(db_url: str | None) -> bool:
    return bool(db_url) and proj_service.is_configured(db_url)


async def db_descriptor(user_id: str, session: dict) -> dict:
    """Non-raising summary of a session's primary DB for the UI.

    Returns {"has_db": bool, "db_kind": "project"|"external"|None, "db_label": str|None}.
    No DSN is ever returned — db_label is a project name or '<database>@<host>'.
    """
    project_id = session.get("project_id")

    # Project-bound session → the project's own DB (owner OR shared-with).
    if project_id:
        proj = await proj_repo.get_accessible_project(project_id, user_id)
        has_db = _configured((proj or {}).get("db_url"))
        label = (proj or {}).get("name") if has_db else None
        return {"has_db": has_db, "db_kind": "project" if has_db else None, "db_label": label}

    # Global session → the user's active external DB.
    db_url = await auth_repo.get_active_db_url(user_id)
    has_db = _configured(db_url)
    return {
        "has_db": has_db,
        "db_kind": "external" if has_db else None,
        "db_label": _external_label(db_url) if has_db else None,
    }
