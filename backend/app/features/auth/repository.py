from __future__ import annotations

from app.db import get_pool


async def upsert_user(google_sub: str, email: str, name: str) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO users (google_sub, email, name)
        VALUES ($1, $2, $3)
        ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email, name = EXCLUDED.name
        RETURNING google_sub, id, email, name, is_admin, disabled_at
        """,
        google_sub, email, name,
    )
    return dict(row)


async def get_user(google_sub: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT google_sub, id, email, name, is_admin, disabled_at FROM users WHERE google_sub = $1",
        google_sub,
    )
    return dict(row) if row else None


async def get_active_db_url(google_sub: str) -> str | None:
    pool = get_pool()
    return await pool.fetchval("SELECT active_db_url FROM users WHERE google_sub = $1", google_sub)


async def set_active_db_url(google_sub: str, db_url: str | None) -> None:
    pool = get_pool()
    await pool.execute("UPDATE users SET active_db_url = $2 WHERE google_sub = $1", google_sub, db_url)
