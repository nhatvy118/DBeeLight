from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg

from internal.utils.token_crypto import decrypt_token, encrypt_token

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
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_in: int | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """
        Insert user if new; otherwise update name + email + Google tokens.
        Tokens are encrypted at rest. ``expires_in`` (seconds) is converted
        to an absolute ``expires_at`` timestamp.

        ``refresh_token`` is only included by Google when the user goes
        through the full consent flow (``access_type=offline`` + first auth,
        or ``prompt=consent`` re-auth). On re-login without consent, Google
        omits it — so we ``COALESCE`` to keep whatever we already had.
        """
        logger.info(
            "Repository: Upserting user google_sub=%s name=%s email=%s "
            "(access_token=%s refresh_token=%s)",
            google_sub, name, email,
            "present" if access_token else "absent",
            "present" if refresh_token else "absent",
        )

        google_sub = (google_sub or "").strip()
        if not google_sub:
            logger.error("Repository: google_sub is required but was empty")
            raise ValueError("google_sub is required")

        name = (name or "").strip() or "Unknown"
        email_norm = (email or "").strip().lower() or None
        encrypted_access = encrypt_token(access_token) if access_token else None
        encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None
        expires_at: datetime | None = None
        if expires_in and expires_in > 0:
            expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(expires_in))

        query = """
        INSERT INTO users (
            name, google_sub, email,
            google_access_token, google_refresh_token,
            google_token_expires_at, google_token_scope
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (google_sub)
        DO UPDATE SET
            name = EXCLUDED.name,
            email = COALESCE(EXCLUDED.email, users.email),
            google_access_token = COALESCE(EXCLUDED.google_access_token, users.google_access_token),
            google_refresh_token = COALESCE(EXCLUDED.google_refresh_token, users.google_refresh_token),
            google_token_expires_at = COALESCE(EXCLUDED.google_token_expires_at, users.google_token_expires_at),
            google_token_scope = COALESCE(EXCLUDED.google_token_scope, users.google_token_scope)
        RETURNING id, name, google_sub, email
        """

        try:
            async with self._pool.acquire() as conn:
                row: Optional[asyncpg.Record] = await conn.fetchrow(
                    query,
                    name, google_sub, email_norm,
                    encrypted_access, encrypted_refresh,
                    expires_at, scope,
                )
                if row is None:
                    logger.error("Repository: UPSERT query returned no row")
                    raise RuntimeError("Failed to upsert user")
                logger.info(f"Repository: User upserted successfully, id={row.get('id')}")
                return dict(row)
        except Exception as e:
            logger.error(f"Repository: Database error upserting user: {e}", exc_info=True)
            raise

    async def find_by_email(self, email: str) -> Optional[dict[str, Any]]:
        """Look up a user by email (case-insensitive). Returns None if not found."""
        e = (email or "").strip().lower()
        if not e:
            return None
        query = "SELECT id, name, google_sub, email FROM users WHERE LOWER(email) = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, e)
            return dict(row) if row else None

    async def find_by_google_sub(self, google_sub: str) -> Optional[dict[str, Any]]:
        gs = (google_sub or "").strip()
        if not gs:
            return None
        query = "SELECT id, name, google_sub, email FROM users WHERE google_sub = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, gs)
            return dict(row) if row else None

    async def get_google_tokens(self, google_sub: str) -> Optional[dict[str, Any]]:
        """Return decrypted Google tokens for a user, or None if not stored.

        Output: ``{access_token, refresh_token, expires_at, scope}``.
        Caller is responsible for refreshing if ``expires_at`` is past.
        """
        gs = (google_sub or "").strip()
        if not gs:
            return None
        query = """
        SELECT google_access_token, google_refresh_token,
               google_token_expires_at, google_token_scope
        FROM users WHERE google_sub = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, gs)
        if not row:
            return None
        if not row["google_access_token"] and not row["google_refresh_token"]:
            return None
        return {
            "access_token": decrypt_token(row["google_access_token"]),
            "refresh_token": decrypt_token(row["google_refresh_token"]),
            "expires_at": row["google_token_expires_at"],
            "scope": row["google_token_scope"],
        }

    async def update_google_access_token(
        self,
        *,
        google_sub: str,
        access_token: str,
        expires_in: int,
    ) -> None:
        """Update access_token + expires_at after a refresh. ``refresh_token``
        usually does NOT rotate, so we don't touch it here."""
        gs = (google_sub or "").strip()
        if not gs:
            return
        encrypted = encrypt_token(access_token)
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(expires_in or 3600))
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET google_access_token = $2,
                    google_token_expires_at = $3
                WHERE google_sub = $1
                """,
                gs, encrypted, expires_at,
            )
