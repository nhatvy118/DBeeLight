from __future__ import annotations

import json
import logging
import secrets
import uuid as _uuid
from datetime import datetime
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

VALID_PERMISSIONS = {"view_only", "read_data", "edit_data"}


class ChatShareRepository:
    """DB I/O for chat session sharing.

    Tables: ``chat_shares`` (one per share event by an owner) and
    ``chat_share_recipients`` (one per recipient + permission).
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(32)

    async def create_share(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        project_id: str,
        recipients: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Create a share + N recipients atomically.

        recipients: list of {email, permission}. Permission must be in VALID_PERMISSIONS.
        Returns: {share_id, recipients: [{id, email, permission, accept_token}, ...]}
        """
        if not recipients:
            raise ValueError("At least one recipient is required")

        for r in recipients:
            perm = (r.get("permission") or "").strip()
            if perm not in VALID_PERMISSIONS:
                raise ValueError(f"Invalid permission: {perm!r}")
            if not (r.get("email") or "").strip():
                raise ValueError("Recipient email is required")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                share_row = await conn.fetchrow(
                    """
                    INSERT INTO chat_shares (session_id, project_id, owner_user_id)
                    VALUES ($1, $2, $3)
                    RETURNING id, created_at
                    """,
                    session_id,
                    project_id,
                    owner_user_id,
                )
                share_id = share_row["id"]

                created: list[dict[str, Any]] = []
                for r in recipients:
                    email = r["email"].strip().lower()
                    perm = r["permission"].strip()
                    token = self._generate_token()
                    rec_row = await conn.fetchrow(
                        """
                        INSERT INTO chat_share_recipients
                            (share_id, recipient_email, permission, accept_token)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id, recipient_email, permission, accept_token
                        """,
                        share_id,
                        email,
                        perm,
                        token,
                    )
                    created.append(dict(rec_row))

                return {
                    "share_id": str(share_id),
                    "session_id": session_id,
                    "project_id": project_id,
                    "created_at": share_row["created_at"],
                    "recipients": [
                        {
                            "id": str(r["id"]),
                            "email": r["recipient_email"],
                            "permission": r["permission"],
                            "accept_token": r["accept_token"],
                        }
                        for r in created
                    ],
                }

    async def get_recipient_by_token(self, accept_token: str) -> Optional[dict[str, Any]]:
        """Fetch full recipient + share + session metadata by accept token.

        Returns None if not found. Caller should check ``revoked_at`` and
        ``share_revoked_at`` before treating it as valid.
        """
        token = (accept_token or "").strip()
        if not token:
            return None
        query = """
        SELECT
            r.id                AS recipient_id,
            r.share_id          AS share_id,
            r.recipient_email   AS recipient_email,
            r.recipient_user_id AS recipient_user_id,
            r.permission        AS permission,
            r.accept_token      AS accept_token,
            r.forked_session_id AS forked_session_id,
            r.accepted_at       AS accepted_at,
            r.revoked_at        AS revoked_at,
            s.id                AS share_id2,
            s.session_id        AS session_id,
            s.project_id        AS project_id,
            s.owner_user_id     AS owner_user_id,
            s.created_at        AS share_created_at,
            s.revoked_at        AS share_revoked_at,
            sess.session_name   AS session_name
        FROM chat_share_recipients r
        JOIN chat_shares s ON s.id = r.share_id
        LEFT JOIN session sess ON sess.id = s.session_id
        WHERE r.accept_token = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, token)
            return dict(row) if row else None

    async def get_share_permission_for_session(
        self, forked_session_id: str
    ) -> Optional[dict[str, Any]]:
        """Return {permission, recipient_id, share_id, owner_user_id, recipient_user_id, revoked}
        for a forked session, or None if the session is not a fork.

        ``revoked`` is True if either the recipient row or the share row is revoked.
        """
        if not forked_session_id:
            return None
        query = """
        SELECT
            r.id              AS recipient_id,
            r.permission      AS permission,
            r.recipient_user_id AS recipient_user_id,
            r.revoked_at      AS recipient_revoked_at,
            s.id              AS share_id,
            s.owner_user_id   AS owner_user_id,
            s.session_id      AS source_session_id,
            s.project_id      AS project_id,
            s.revoked_at      AS share_revoked_at
        FROM session sess
        JOIN chat_share_recipients r ON r.id = sess.share_recipient_id
        JOIN chat_shares s ON s.id = r.share_id
        WHERE sess.id = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, forked_session_id)
            if not row:
                return None
            d = dict(row)
            d["revoked"] = bool(d["recipient_revoked_at"]) or bool(d["share_revoked_at"])
            return d

    async def fork_session_for_recipient(
        self,
        *,
        recipient_id: str,
        recipient_google_sub: str,
        recipient_email: str,
    ) -> dict[str, Any]:
        """Snapshot-fork the source session into a new session owned by recipient.

        Idempotent: if recipient has already accepted, returns existing forked session.
        Validates that recipient_google_sub is the right user (matches by email).
        Returns {session_id, project_id, permission}.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                rec_row = await conn.fetchrow(
                    """
                    SELECT
                        r.id, r.share_id, r.recipient_email, r.recipient_user_id,
                        r.permission, r.accepted_at, r.forked_session_id, r.revoked_at,
                        s.session_id AS source_session_id,
                        s.project_id AS project_id,
                        s.revoked_at AS share_revoked_at
                    FROM chat_share_recipients r
                    JOIN chat_shares s ON s.id = r.share_id
                    WHERE r.id = $1
                    FOR UPDATE OF r
                    """,
                    recipient_id,
                )
                if rec_row is None:
                    raise LookupError("Share recipient not found")

                if rec_row["revoked_at"] is not None or rec_row["share_revoked_at"] is not None:
                    raise PermissionError("This share has been revoked")

                # Email match (case-insensitive). The recipient must have logged in
                # with the same email the owner shared to.
                if (rec_row["recipient_email"] or "").lower() != (recipient_email or "").lower():
                    raise PermissionError(
                        "This share was not addressed to your account email"
                    )

                # Already accepted: return existing fork (idempotent).
                if rec_row["forked_session_id"] and rec_row["accepted_at"]:
                    return {
                        "session_id": rec_row["forked_session_id"],
                        "project_id": str(rec_row["project_id"]),
                        "permission": rec_row["permission"],
                        "already_accepted": True,
                    }

                # Snapshot the source session content.
                src = await conn.fetchrow(
                    """
                    SELECT id, content, project_id, session_name
                    FROM session
                    WHERE id = $1
                    """,
                    rec_row["source_session_id"],
                )
                if src is None:
                    raise LookupError("Source session no longer exists")

                # Generate a new session id matching the existing convention
                # used by session_manager.create_session: 8-char hex prefix of
                # a UUID. Retry on the (very unlikely) collision.
                new_session_id: str | None = None
                for _ in range(5):
                    candidate = str(_uuid.uuid4())[:8]
                    exists = await conn.fetchval(
                        "SELECT 1 FROM session WHERE id = $1", candidate
                    )
                    if not exists:
                        new_session_id = candidate
                        break
                if new_session_id is None:
                    new_session_id = str(_uuid.uuid4())  # fallback to full UUID

                src_name = src["session_name"] or "Shared chat"
                new_name = f"Shared: {src_name}" if not src_name.startswith("Shared:") else src_name

                # Snapshot the content but rewrite session_id (and created_at) so
                # downstream lookups via JSONB (sessions list, etc.) return the
                # *new* session id, not the source's.
                content = src["content"]
                if isinstance(content, str):
                    try:
                        content_dict = json.loads(content)
                    except json.JSONDecodeError:
                        content_dict = {}
                elif isinstance(content, dict):
                    content_dict = dict(content)
                else:
                    content_dict = {}

                content_dict["session_id"] = new_session_id
                content_dict["created_at"] = datetime.now().isoformat()
                content_dict["forked_from_session_id"] = rec_row["source_session_id"]
                content_param = json.dumps(content_dict)

                await conn.execute(
                    """
                    INSERT INTO session
                        (id, user_id, content, project_id, session_name, share_recipient_id)
                    VALUES ($1, $2, $3::jsonb, $4, $5, $6)
                    """,
                    new_session_id,
                    recipient_google_sub,
                    content_param,
                    src["project_id"],
                    new_name,
                    recipient_id,
                )

                # Mark recipient as accepted.
                await conn.execute(
                    """
                    UPDATE chat_share_recipients
                    SET accepted_at = CURRENT_TIMESTAMP,
                        recipient_user_id = $2,
                        forked_session_id = $3
                    WHERE id = $1
                    """,
                    recipient_id,
                    recipient_google_sub,
                    new_session_id,
                )

                return {
                    "session_id": new_session_id,
                    "project_id": str(rec_row["project_id"]),
                    "permission": rec_row["permission"],
                    "already_accepted": False,
                }

    async def list_sent_shares(self, owner_google_sub: str) -> list[dict[str, Any]]:
        """List shares the owner has created, with recipient details."""
        query = """
        SELECT
            s.id AS share_id,
            s.session_id,
            s.project_id,
            s.created_at,
            s.revoked_at,
            sess.session_name,
            r.id AS recipient_id,
            r.recipient_email,
            r.permission,
            r.accept_token,
            r.accepted_at,
            r.revoked_at AS recipient_revoked_at,
            r.forked_session_id,
            r.email_sent_at,
            r.email_error
        FROM chat_shares s
        JOIN chat_share_recipients r ON r.share_id = s.id
        LEFT JOIN session sess ON sess.id = s.session_id
        WHERE s.owner_user_id = $1
        ORDER BY s.created_at DESC, r.recipient_email ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, owner_google_sub)

        # Group by share_id.
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            sid = str(row["share_id"])
            if sid not in out:
                out[sid] = {
                    "share_id": sid,
                    "session_id": row["session_id"],
                    "project_id": str(row["project_id"]),
                    "session_name": row["session_name"],
                    "created_at": row["created_at"],
                    "revoked_at": row["revoked_at"],
                    "recipients": [],
                }
            out[sid]["recipients"].append({
                "id": str(row["recipient_id"]),
                "email": row["recipient_email"],
                "permission": row["permission"],
                "accept_token": row["accept_token"],
                "accepted_at": row["accepted_at"],
                "revoked_at": row["recipient_revoked_at"],
                "forked_session_id": row["forked_session_id"],
                "email_sent_at": row["email_sent_at"],
                "email_error": row["email_error"],
            })
        return list(out.values())

    async def get_recipient_for_owner(
        self, *, recipient_id: str, owner_google_sub: str
    ) -> Optional[dict[str, Any]]:
        """Fetch one recipient row, but only if it belongs to a share the
        given owner created. Used by the resend-email endpoint to authorize
        the sender."""
        query = """
        SELECT
            r.id AS recipient_id,
            r.recipient_email,
            r.permission,
            r.accept_token,
            r.email_sent_at,
            r.email_error,
            s.session_id,
            sess.session_name
        FROM chat_share_recipients r
        JOIN chat_shares s ON s.id = r.share_id
        LEFT JOIN session sess ON sess.id = s.session_id
        WHERE r.id = $1
          AND s.owner_user_id = $2
          AND s.revoked_at IS NULL
          AND r.revoked_at IS NULL
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, recipient_id, owner_google_sub)
            return dict(row) if row else None

    async def mark_email_sent(self, recipient_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chat_share_recipients
                SET email_sent_at = CURRENT_TIMESTAMP,
                    email_error = NULL
                WHERE id = $1
                """,
                recipient_id,
            )

    async def mark_email_failed(self, recipient_id: str, error: str) -> None:
        # Truncate to a sensible length so a giant traceback doesn't bloat
        # the DB row or the JSON we send back to the UI.
        msg = (error or "Unknown error")[:500]
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chat_share_recipients
                SET email_error = $2,
                    email_sent_at = NULL
                WHERE id = $1
                """,
                recipient_id, msg,
            )

    async def list_received_shares(
        self, recipient_email: str, recipient_google_sub: str | None = None
    ) -> list[dict[str, Any]]:
        """List shares addressed to a given email (the user's login email).

        Includes both pending (not accepted) and accepted shares. Excludes revoked.
        """
        email = (recipient_email or "").strip().lower()
        if not email:
            return []
        query = """
        SELECT
            r.id AS recipient_id,
            r.recipient_email,
            r.permission,
            r.accept_token,
            r.accepted_at,
            r.forked_session_id,
            s.id AS share_id,
            s.session_id,
            s.project_id,
            s.created_at,
            s.owner_user_id,
            sess.session_name,
            owner.name AS owner_name,
            owner.email AS owner_email
        FROM chat_share_recipients r
        JOIN chat_shares s ON s.id = r.share_id
        LEFT JOIN session sess ON sess.id = s.session_id
        LEFT JOIN users owner ON owner.google_sub = s.owner_user_id
        WHERE LOWER(r.recipient_email) = $1
          AND r.revoked_at IS NULL
          AND s.revoked_at IS NULL
        ORDER BY s.created_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, email)
        return [
            {
                "recipient_id": str(row["recipient_id"]),
                "share_id": str(row["share_id"]),
                "permission": row["permission"],
                "accept_token": row["accept_token"],
                "accepted_at": row["accepted_at"],
                "forked_session_id": row["forked_session_id"],
                "session_id": row["session_id"],
                "project_id": str(row["project_id"]),
                "session_name": row["session_name"],
                "shared_at": row["created_at"],
                "owner_name": row["owner_name"],
                "owner_email": row["owner_email"],
            }
            for row in rows
        ]

    async def revoke_share(self, *, share_id: str, owner_google_sub: str) -> bool:
        """Revoke an entire share event (all recipients). Owner-only."""
        query = """
        UPDATE chat_shares
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE id = $1 AND owner_user_id = $2 AND revoked_at IS NULL
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(query, share_id, owner_google_sub)
            return not result.endswith("0")

    async def revoke_recipient(self, *, recipient_id: str, owner_google_sub: str) -> bool:
        """Revoke a single recipient. Owner-only (verified via JOIN to chat_shares)."""
        query = """
        UPDATE chat_share_recipients r
        SET revoked_at = CURRENT_TIMESTAMP
        FROM chat_shares s
        WHERE r.id = $1
          AND r.share_id = s.id
          AND s.owner_user_id = $2
          AND r.revoked_at IS NULL
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(query, recipient_id, owner_google_sub)
            return not result.endswith("0")

    async def get_owner_for_recipient_project(
        self, *, recipient_google_sub: str, project_id: str
    ) -> Optional[str]:
        """If the recipient has an active (accepted, non-revoked) share for a
        session in ``project_id``, return that share's owner google_sub.

        Used to bypass owner-only checks (e.g. ``ProjectRepository.get_project_by_id``)
        on derived flows like Superset guest-token minting, where the recipient
        legitimately needs to access a resource scoped to the owner.
        """
        if not recipient_google_sub or not project_id:
            return None
        query = """
        SELECT s.owner_user_id
        FROM chat_share_recipients r
        JOIN chat_shares s ON s.id = r.share_id
        WHERE r.recipient_user_id = $1
          AND s.project_id = $2::uuid
          AND r.revoked_at IS NULL
          AND s.revoked_at IS NULL
        LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, recipient_google_sub, project_id)
            return row["owner_user_id"] if row else None

    async def verify_session_owner(
        self, *, session_id: str, owner_google_sub: str
    ) -> Optional[dict[str, Any]]:
        """Return the session row only if it is owned by ``owner_google_sub``
        and is NOT itself a forked session (you can't share a forked session).
        """
        query = """
        SELECT id, user_id, project_id, session_name, share_recipient_id
        FROM session
        WHERE id = $1 AND user_id = $2
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, session_id, owner_google_sub)
            if not row:
                return None
            if row["share_recipient_id"] is not None:
                # Recipient cannot re-share.
                return None
            return dict(row)
