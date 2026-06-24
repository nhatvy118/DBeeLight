from __future__ import annotations
import logging

from app.db import get_pool

logger = logging.getLogger("features.auth.repository")


_RETURN = "google_sub, id, email, name, role, disabled_at"


async def resolve_login(google_sub: str, email: str, name: str) -> dict | None:
    """Invite-only login. Returns the user row to sign in, or None if this person is not allowed
    (no existing account, no pending invite, not a bootstrap admin).

    Order: existing user → bootstrap admin → pending invite (consumed). Existing users keep their
    role; bootstrap admins are created/kept as admin; invited emails get the invite's role.
    """
    logger.info("→ resolve_login(google_sub=%r email=%r)", google_sub, email)  # autolog
    from app.config import get_settings

    pool = get_pool()
    # 1) existing user → refresh profile, keep role.
    row = await pool.fetchrow(
        f"UPDATE users SET email=$2, name=$3 WHERE google_sub=$1 RETURNING {_RETURN}",
        google_sub, email, name,
    )
    if row:
        return dict(row)

    # 2) bootstrap admin email → always allowed, as admin (never lock the operator out).
    if email and email.lower() in get_settings().bootstrap_admins:
        row = await pool.fetchrow(
            f"INSERT INTO users (google_sub, email, name, role) VALUES ($1,$2,$3,'admin') "
            f"RETURNING {_RETURN}",
            google_sub, email, name,
        )
        return dict(row)

    # 3) pending invite → create the user with the invited role, then consume the invite.
    inv = await pool.fetchrow("SELECT role FROM invites WHERE lower(email)=lower($1)", email or "")
    if inv:
        row = await pool.fetchrow(
            f"INSERT INTO users (google_sub, email, name, role) VALUES ($1,$2,$3,$4) "
            f"RETURNING {_RETURN}",
            google_sub, email, name, inv["role"],
        )
        await pool.execute("DELETE FROM invites WHERE lower(email)=lower($1)", email)
        return dict(row)

    # 4) not invited → rejected.
    return None


async def get_user(google_sub: str) -> dict | None:
    logger.info("→ get_user(google_sub=%r)", google_sub)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        f"SELECT {_RETURN} FROM users WHERE google_sub = $1", google_sub,
    )
    return dict(row) if row else None


async def get_user_by_email(email: str) -> dict | None:
    """Look up an existing (joined) user by email — used when sharing a project by email."""
    pool = get_pool()
    row = await pool.fetchrow(
        f"SELECT {_RETURN} FROM users WHERE lower(email) = lower($1)", email or "",
    )
    return dict(row) if row else None


