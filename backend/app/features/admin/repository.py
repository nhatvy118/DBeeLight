from __future__ import annotations
import logging

from app.db import get_pool

logger = logging.getLogger("features.admin.repository")

ROLES = ("admin", "technical", "viewer")


async def get_user_role(google_sub: str) -> dict | None:
    logger.info("→ get_user_role(google_sub=%r)", google_sub)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, role, disabled_at FROM users WHERE google_sub=$1", google_sub
    )
    return dict(row) if row else None


async def list_users_with_stats() -> list[dict]:
    """Active/disabled accounts with their role + usage stats."""
    logger.info("→ list_users_with_stats()")  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT u.id, u.name, u.email, u.role, u.created_at, u.disabled_at,
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


async def list_pending_invites() -> list[dict]:
    """Invited emails that have NOT signed in yet (invite-only access)."""
    logger.info("→ list_pending_invites()")  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, email, role, created_at FROM invites ORDER BY created_at ASC"
    )
    return [dict(r) for r in rows]


async def get_overview_stats() -> dict:
    logger.info("→ get_overview_stats()")  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT (SELECT COUNT(*) FROM users) AS total_users,
               (SELECT COUNT(*) FROM users WHERE disabled_at IS NOT NULL) AS disabled_users,
               (SELECT COUNT(*) FROM users WHERE role='admin') AS admin_users,
               (SELECT COUNT(*) FROM users WHERE role='technical') AS technical_users,
               (SELECT COUNT(*) FROM users WHERE role='viewer') AS viewer_users,
               (SELECT COUNT(*) FROM invites) AS pending_invites,
               (SELECT COUNT(*) FROM projects) AS total_projects,
               (SELECT COUNT(*) FROM sessions) AS total_sessions,
               (SELECT COALESCE(SUM(size_bytes),0) FROM files) AS total_storage_bytes
        """
    )
    return dict(row)


async def set_user_role(user_id: int, role: str) -> dict | None:
    logger.info("→ set_user_role(user_id=%r role=%r)", user_id, role)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE users SET role=$2 WHERE id=$1 RETURNING id, role", user_id, role
    )
    return dict(row) if row else None


async def set_user_disabled(user_id: int, disabled: bool) -> dict | None:
    logger.info("→ set_user_disabled(user_id=%r disabled=%r)", user_id, disabled)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE users SET disabled_at = CASE WHEN $2 THEN now() ELSE NULL END "
        "WHERE id=$1 RETURNING id, disabled_at",
        user_id, disabled,
    )
    return dict(row) if row else None


async def email_taken(email: str) -> bool:
    """True if a user already exists with this email (so we don't invite a duplicate)."""
    pool = get_pool()
    return bool(await pool.fetchval("SELECT 1 FROM users WHERE lower(email)=lower($1)", email))


async def create_invite(email: str, role: str, invited_by: str) -> dict:
    """Pre-authorise an email with a role. Upserts so re-inviting just updates the role."""
    logger.info("→ create_invite(email=%r role=%r)", email, role)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO invites (email, role, invited_by) VALUES ($1, $2, $3)
        ON CONFLICT (lower(email)) DO UPDATE SET role = EXCLUDED.role
        RETURNING id, email, role, created_at
        """,
        email, role, invited_by,
    )
    return dict(row)


async def set_invite_role(invite_id: int, role: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE invites SET role=$2 WHERE id=$1 RETURNING id, role", invite_id, role
    )
    return dict(row) if row else None


async def revoke_invite(invite_id: int) -> bool:
    logger.info("→ revoke_invite(invite_id=%r)", invite_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow("DELETE FROM invites WHERE id=$1 RETURNING id", invite_id)
    return row is not None
