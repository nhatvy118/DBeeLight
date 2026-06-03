from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


class UserRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def upsert_user(
        self,
        *,
        google_sub: str,
        name: str,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Insert user if new; otherwise update name + email."""
        logger.info(
            "Repository: Upserting user google_sub=%s name=%s email=%s",
            google_sub, name, email,
        )

        google_sub = (google_sub or "").strip()
        if not google_sub:
            logger.error("Repository: google_sub is required but was empty")
            raise ValueError("google_sub is required")

        name = (name or "").strip() or "Unknown"
        email_norm = (email or "").strip().lower() or None

        query = """
        INSERT INTO users (name, google_sub, email)
        VALUES ($1, $2, $3)
        ON CONFLICT (google_sub)
        DO UPDATE SET
            name = EXCLUDED.name,
            email = COALESCE(EXCLUDED.email, users.email)
        RETURNING id, name, google_sub, email
        """

        try:
            async with self._pool.acquire() as conn:
                row: Optional[asyncpg.Record] = await conn.fetchrow(
                    query,
                    name, google_sub, email_norm,
                )
                if row is None:
                    logger.error("Repository: UPSERT query returned no row")
                    raise RuntimeError("Failed to upsert user")
                logger.info(f"Repository: User upserted successfully, id={row.get('id')}")
                return dict(row)
        except Exception as e:
            logger.error(f"Repository: Database error upserting user: {e}", exc_info=True)
            raise

