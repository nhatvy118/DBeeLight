from __future__ import annotations

import uuid

from app.db import get_pool

_PLACEHOLDER = "placeholder://not-configured"


async def create_project(user_id: str, name: str, description: str) -> dict:
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
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, description, db_url FROM projects WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_project(project_id: str, user_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, description, db_url FROM projects WHERE id = $1 AND user_id = $2",
        project_id, user_id,
    )
    return dict(row) if row else None


async def set_db_url(project_id: str, user_id: str, db_url: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE projects SET db_url = $3 WHERE id = $1 AND user_id = $2",
        project_id, user_id, db_url,
    )


async def delete_project(project_id: str, user_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM projects WHERE id = $1 AND user_id = $2 RETURNING id, db_url",
        project_id, user_id,
    )
    return dict(row) if row else None
