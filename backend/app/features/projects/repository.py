from __future__ import annotations

import logging
import uuid

from app.db import get_pool

logger = logging.getLogger("projects.repo")

_PLACEHOLDER = "placeholder://not-configured"


async def create_project(user_id: str, name: str, description: str) -> dict:
    logger.info("→ create_project(user_id=%r name=%r description=%r)", user_id, name, description)  # autolog
    pool = get_pool()
    pid = str(uuid.uuid4())
    row = await pool.fetchrow(
        """
        INSERT INTO projects (id, name, description, user_id, db_url)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, name, description, db_url
        """,
        pid, name, description, user_id, _PLACEHOLDER,
    )
    return dict(row)


async def list_projects(user_id: str) -> list[dict]:
    logger.info("→ list_projects(user_id=%r)", user_id)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, description, db_url FROM projects WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_project(project_id: str, user_id: str) -> dict | None:
    logger.info("→ get_project(project_id=%r user_id=%r)", project_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, description, db_url FROM projects WHERE id = $1 AND user_id = $2",
        project_id, user_id,
    )
    return dict(row) if row else None


async def get_db_url_any(project_id: str) -> str | None:
    """Project db_url by id only (NO owner filter). For shared/forked sessions where the
    requester is not the project owner — the caller is responsible for the access check."""
    logger.info("→ get_db_url_any(project_id=%r)", project_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow("SELECT db_url FROM projects WHERE id = $1", project_id)
    return row["db_url"] if row else None


async def get_description_any(project_id: str) -> str | None:
    """Project description by id only (NO owner filter) — used as the database-level context
    for SQL generation. Returns None for synthetic/external scopes with no project row."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT description FROM projects WHERE id = $1", project_id)
    return (row["description"] or None) if row else None


async def set_db_url(project_id: str, user_id: str, db_url: str) -> None:
    logger.info("→ set_db_url(project_id=%r user_id=%r db_url=***)", project_id, user_id)  # autolog
    pool = get_pool()
    await pool.execute(
        "UPDATE projects SET db_url = $3 WHERE id = $1 AND user_id = $2",
        project_id, user_id, db_url,
    )


async def delete_project(project_id: str, user_id: str) -> dict | None:
    logger.info("→ delete_project(project_id=%r user_id=%r)", project_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM projects WHERE id = $1 AND user_id = $2 RETURNING id, db_url",
        project_id, user_id,
    )
    return dict(row) if row else None
