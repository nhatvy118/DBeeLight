from __future__ import annotations

from typing import Any, Optional

import asyncpg


class UserRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def upsert_user(self, *, google_sub: str, name: str) -> dict[str, Any]:
        """
        Insert user if new; otherwise update name. Returns the persisted row.
        Requires unique constraint on users.google_sub.
        """
        google_sub = (google_sub or "").strip()
        if not google_sub:
            raise ValueError("google_sub is required")

        name = (name or "").strip() or "Unknown"

        query = """
        INSERT INTO users (name, google_sub)
        VALUES ($1, $2)
        ON CONFLICT (google_sub)
        DO UPDATE SET name = EXCLUDED.name
        RETURNING id, name, google_sub
        """

        async with self._pool.acquire() as conn:
            row: Optional[asyncpg.Record] = await conn.fetchrow(query, name, google_sub)
            if row is None:
                raise RuntimeError("Failed to upsert user")
            return dict(row)

