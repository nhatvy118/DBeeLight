from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


class AdminRepository:
    """Read/aggregate queries for the admin dashboard.

    Per-user resources (projects, sessions, files) key off ``users.google_sub``,
    so the stat joins use that rather than ``users.id``.
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_user_role(self, user_id: int) -> Optional[dict[str, Any]]:
        """Return ``{is_admin, disabled_at}`` for the user id, or None if missing."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, is_admin, disabled_at FROM users WHERE id = $1",
                user_id,
            )
            return dict(row) if row else None

    async def list_users_with_stats(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            u.id,
            u.name,
            u.email,
            u.google_sub,
            u.created_at,
            u.is_admin,
            u.disabled_at,
            COALESCE(p.cnt, 0)   AS project_count,
            COALESCE(s.cnt, 0)   AS session_count,
            COALESCE(f.bytes, 0) AS storage_bytes
        FROM users u
        LEFT JOIN (SELECT user_id, COUNT(*) AS cnt FROM projects GROUP BY user_id) p
            ON p.user_id = u.google_sub
        LEFT JOIN (SELECT user_id, COUNT(*) AS cnt FROM session GROUP BY user_id) s
            ON s.user_id = u.google_sub
        LEFT JOIN (SELECT user_id, SUM(size_bytes) AS bytes FROM files GROUP BY user_id) f
            ON f.user_id = u.google_sub
        ORDER BY u.created_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def get_overview_stats(self) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM users)                                AS total_users,
                    (SELECT COUNT(*) FROM users WHERE disabled_at IS NOT NULL)  AS disabled_users,
                    (SELECT COUNT(*) FROM users WHERE is_admin)                 AS admin_users,
                    (SELECT COUNT(*) FROM projects)                             AS total_projects,
                    (SELECT COUNT(*) FROM session)                             AS total_sessions,
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM files)           AS total_storage_bytes
                """
            )
            return dict(row) if row else {}

    async def set_user_disabled(self, user_id: int, disabled: bool) -> Optional[dict[str, Any]]:
        """Set/clear ``disabled_at``. Returns the updated row or None if not found."""
        query = (
            "UPDATE users SET disabled_at = CASE WHEN $2 THEN CURRENT_TIMESTAMP ELSE NULL END "
            "WHERE id = $1 RETURNING id, disabled_at"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, user_id, disabled)
            return dict(row) if row else None
