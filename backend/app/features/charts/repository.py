"""Persistence for saved charts (a project's dashboard = its saved_charts rows)."""
from __future__ import annotations

import json
import logging
import uuid

from app.db import get_pool

logger = logging.getLogger("features.charts.repository")


async def insert_chart(
    user_id: str, project_id: str, title: str, sql: str, mark: str,
    encoding: dict, transform: list | None, layout: str | None,
) -> dict:
    logger.info("→ insert_chart(user_id=%r project_id=%r title=%r mark=%r)", user_id, project_id, title, mark)  # autolog
    pool = get_pool()
    cid = str(uuid.uuid4())
    row = await pool.fetchrow(
        """
        INSERT INTO saved_charts (id, user_id, project_id, title, sql, mark, encoding, transform, layout, position)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                COALESCE((SELECT MAX(position) + 1 FROM saved_charts WHERE project_id = $3), 0))
        RETURNING id, title, mark, layout, position, created_at
        """,
        cid, user_id, project_id, title, sql, mark,
        json.dumps(encoding), json.dumps(transform) if transform else None, layout,
    )
    return dict(row)


async def list_for_project(project_id: str, user_id: str) -> list[dict]:
    """Chart definitions for a project's dashboard (ownership-scoped)."""
    logger.info("→ list_for_project(project_id=%r user_id=%r)", project_id, user_id)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, sql, mark, encoding, transform, layout, position, created_at
        FROM saved_charts WHERE project_id = $1 AND user_id = $2
        ORDER BY position ASC, created_at ASC
        """,
        project_id, user_id,
    )
    return [dict(r) for r in rows]


async def find_chart(project_id: str, user_id: str, sql: str, mark: str) -> dict | None:
    """An existing chart with the same SQL + mark in this project (used to dedupe saves)."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, title FROM saved_charts WHERE project_id = $1 AND user_id = $2 AND sql = $3 AND mark = $4 LIMIT 1",
        project_id, user_id, sql, mark,
    )
    return dict(row) if row else None


async def get_chart(chart_id: str, user_id: str) -> dict | None:
    logger.info("→ get_chart(chart_id=%r user_id=%r)", chart_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, project_id, title, sql, mark, encoding, transform, layout "
        "FROM saved_charts WHERE id = $1 AND user_id = $2",
        chart_id, user_id,
    )
    return dict(row) if row else None


async def update_chart(chart_id: str, user_id: str, title: str, sql: str, layout: str | None) -> bool:
    logger.info("→ update_chart(chart_id=%r user_id=%r)", chart_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE saved_charts SET title = $3, sql = $4, layout = $5 "
        "WHERE id = $1 AND user_id = $2 RETURNING id",
        chart_id, user_id, title, sql, layout,
    )
    return row is not None


async def set_positions(project_id: str, user_id: str, ordered_ids: list[str]) -> None:
    """Persist a new chart order: position = index in ordered_ids."""
    logger.info("→ set_positions(project_id=%r n=%d)", project_id, len(ordered_ids))  # autolog
    pool = get_pool()
    async with pool.acquire() as conn:
        for i, cid in enumerate(ordered_ids):
            await conn.execute(
                "UPDATE saved_charts SET position = $1 WHERE id = $2 AND project_id = $3 AND user_id = $4",
                i, cid, project_id, user_id,
            )


async def delete_chart(chart_id: str, user_id: str) -> bool:
    logger.info("→ delete_chart(chart_id=%r user_id=%r)", chart_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM saved_charts WHERE id = $1 AND user_id = $2 RETURNING id", chart_id, user_id
    )
    return row is not None
