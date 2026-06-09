from __future__ import annotations

from app.db import get_pool


async def get_user_role(google_sub: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, is_admin, disabled_at FROM users WHERE google_sub=$1", google_sub
    )
    return dict(row) if row else None


async def list_users_with_stats() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT u.id, u.name, u.email, u.created_at, u.is_admin, u.disabled_at,
               COALESCE(p.cnt,0) AS project_count, COALESCE(s.cnt,0) AS session_count,
               COALESCE(f.bytes,0) AS storage_bytes
        FROM users u
        LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM projects GROUP BY user_id) p ON p.user_id=u.google_sub
        LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM sessions GROUP BY user_id) s ON s.user_id=u.google_sub
        LEFT JOIN (SELECT user_id, SUM(size_bytes) bytes FROM files GROUP BY user_id) f ON f.user_id=u.google_sub
        ORDER BY u.created_at ASC
        """
    )
    return [dict(r) for r in rows]


async def get_overview_stats() -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT (SELECT COUNT(*) FROM users) AS total_users,
               (SELECT COUNT(*) FROM users WHERE disabled_at IS NOT NULL) AS disabled_users,
               (SELECT COUNT(*) FROM users WHERE is_admin) AS admin_users,
               (SELECT COUNT(*) FROM projects) AS total_projects,
               (SELECT COUNT(*) FROM sessions) AS total_sessions,
               (SELECT COALESCE(SUM(size_bytes),0) FROM files) AS total_storage_bytes
        """
    )
    return dict(row)


async def set_user_disabled(user_id: int, disabled: bool) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE users SET disabled_at = CASE WHEN $2 THEN now() ELSE NULL END "
        "WHERE id=$1 RETURNING id, disabled_at",
        user_id, disabled,
    )
    return dict(row) if row else None
