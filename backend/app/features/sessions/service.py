"""Sessions service — read-only helpers that don't belong in the router or repository.

db_descriptor() summarizes a session's project DB for the UI. It mirrors the db_url
resolution in chat.service._authorize, but is non-raising and NEVER exposes the DSN
(only a human label). Every data source is now a project (internal SQLite or external DB),
so "does this session have a DB?" comes from the session's project_id alone.
"""
from __future__ import annotations

import logging

from app.features.projects import repository as proj_repo
from app.features.projects import service as proj_service

logger = logging.getLogger("sessions")


def _configured(db_url: str | None) -> bool:
    return bool(db_url) and proj_service.is_configured(db_url)


async def db_descriptor(user_id: str, session: dict) -> dict:
    """Non-raising summary of a session's project DB for the UI.

    Returns {"has_db": bool, "db_kind": "internal"|"external"|None, "db_label": str|None}.
    No DSN is ever returned — db_label is the project name.
    """
    project_id = session.get("project_id")
    if not project_id:
        # Legacy global session — no project, nothing to query.
        return {"has_db": False, "db_kind": None, "db_label": None}

    proj = await proj_repo.get_accessible_project(project_id, user_id)
    has_db = _configured((proj or {}).get("db_url"))
    if not has_db:
        return {"has_db": False, "db_kind": None, "db_label": None}
    return {"has_db": True, "db_kind": (proj or {}).get("kind") or "internal", "db_label": (proj or {}).get("name")}
