"""DB I/O for chat sharing (full: token, session fork, revoke, email status).

The new design uses sessions + messages (normalized) → fork = clone session + copy messages.
"""
from __future__ import annotations
import logging

import json
import secrets
import uuid

from app.db import get_pool

logger = logging.getLogger("features.share.repository")

VALID_PERMISSIONS = {"view_only", "read_data", "edit_data"}


def _token() -> str:
    logger.info("→ _token()")  # autolog
    return secrets.token_urlsafe(32)


async def verify_session_owner(session_id: str, owner_sub: str) -> dict | None:
    logger.info("→ verify_session_owner(session_id=%r owner_sub=%r)", session_id, owner_sub)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, user_id, project_id, title, share_recipient_id FROM sessions "
        "WHERE id=$1 AND user_id=$2",
        session_id, owner_sub,
    )
    if not row or row["share_recipient_id"] is not None:  # cannot re-share a forked session
        return None
    return dict(row)


async def create_share(owner_sub: str, session_id: str, project_id: str,
                       recipients: list[dict]) -> dict:
    logger.info("→ create_share(owner_sub=%r session_id=%r project_id=%r recipients=%r)", owner_sub, session_id, project_id, recipients)  # autolog
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            share_id = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO chat_shares (id, owner_user_id, session_id, project_id) "
                "VALUES ($1,$2,$3,$4)",
                share_id, owner_sub, session_id, project_id,
            )
            created = []
            for r in recipients:
                rid = str(uuid.uuid4())
                tok = _token()
                await conn.execute(
                    "INSERT INTO chat_share_recipients (id, share_id, recipient_email, permission, accept_token) "
                    "VALUES ($1,$2,$3,$4,$5)",
                    rid, share_id, r["email"], r["permission"], tok,
                )
                created.append({"id": rid, "email": r["email"], "permission": r["permission"],
                                "accept_token": tok})
    return {"share_id": share_id, "session_id": session_id, "project_id": project_id,
            "recipients": created}


async def get_recipient_by_token(token: str) -> dict | None:
    logger.info("→ get_recipient_by_token(token=***)")  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT r.id AS recipient_id, r.recipient_email, r.permission, r.accept_token,
               r.forked_session_id, r.accepted_at, r.revoked_at,
               s.session_id, s.project_id, s.owner_user_id, s.revoked_at AS share_revoked_at,
               sess.title AS session_name
        FROM chat_share_recipients r
        JOIN chat_shares s ON s.id = r.share_id
        LEFT JOIN sessions sess ON sess.id = s.session_id
        WHERE r.accept_token=$1
        """,
        (token or "").strip(),
    )
    return dict(row) if row else None


async def fork_session_for_recipient(recipient_id: str, recipient_sub: str,
                                     recipient_email: str) -> dict:
    logger.info("→ fork_session_for_recipient(recipient_id=%r recipient_sub=%r recipient_email=%r)", recipient_id, recipient_sub, recipient_email)  # autolog
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rec = await conn.fetchrow(
                """
                SELECT r.id, r.recipient_email, r.permission, r.accepted_at, r.forked_session_id,
                       r.revoked_at, s.session_id AS src, s.project_id, s.revoked_at AS share_revoked
                FROM chat_share_recipients r JOIN chat_shares s ON s.id=r.share_id
                WHERE r.id=$1 FOR UPDATE OF r
                """,
                recipient_id,
            )
            if rec is None:
                raise LookupError("Share recipient not found")
            if rec["revoked_at"] is not None or rec["share_revoked"] is not None:
                raise PermissionError("This share has been revoked")
            if (rec["recipient_email"] or "").lower() != (recipient_email or "").lower():
                raise PermissionError("This share was not addressed to your account email")
            if rec["forked_session_id"] and rec["accepted_at"]:
                return {"session_id": rec["forked_session_id"], "project_id": rec["project_id"],
                        "permission": rec["permission"], "already_accepted": True}

            src = await conn.fetchrow("SELECT id, project_id, title FROM sessions WHERE id=$1", rec["src"])
            if src is None:
                raise LookupError("Source session no longer exists")
            new_id = uuid.uuid4().hex[:12]   # short dash-less id (FE distinguishes session vs project)
            name = src["title"] or "Shared chat"
            new_name = name if name.startswith("Shared:") else f"Shared: {name}"
            await conn.execute(
                "INSERT INTO sessions (id, user_id, project_id, title, share_recipient_id) "
                "VALUES ($1,$2,$3,$4,$5)",
                new_id, recipient_sub, src["project_id"], new_name, recipient_id,
            )
            # copy messages (snapshot)
            msgs = await conn.fetch(
                "SELECT role, content, tool_events FROM messages WHERE session_id=$1 ORDER BY created_at ASC",
                rec["src"],
            )
            for m in msgs:
                te = m["tool_events"]
                te = te if isinstance(te, str) else json.dumps(te or [])
                await conn.execute(
                    "INSERT INTO messages (id, session_id, role, content, tool_events) VALUES ($1,$2,$3,$4,$5)",
                    str(uuid.uuid4()), new_id, m["role"], m["content"], te,
                )
            await conn.execute(
                "UPDATE chat_share_recipients SET accepted_at=now(), recipient_user_id=$2, forked_session_id=$3 "
                "WHERE id=$1",
                recipient_id, recipient_sub, new_id,
            )
    return {"session_id": new_id, "project_id": rec["project_id"],
            "permission": rec["permission"], "already_accepted": False}


async def list_sent_shares(owner_sub: str) -> list[dict]:
    logger.info("→ list_sent_shares(owner_sub=%r)", owner_sub)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT s.id AS share_id, s.session_id, s.project_id, s.created_at, s.revoked_at,
               sess.title AS session_name,
               r.id AS recipient_id, r.recipient_email, r.permission, r.accept_token,
               r.accepted_at, r.revoked_at AS recipient_revoked_at, r.forked_session_id,
               r.email_sent_at, r.email_error
        FROM chat_shares s JOIN chat_share_recipients r ON r.share_id=s.id
        LEFT JOIN sessions sess ON sess.id=s.session_id
        WHERE s.owner_user_id=$1 ORDER BY s.created_at DESC, r.recipient_email ASC
        """,
        owner_sub,
    )
    out: dict[str, dict] = {}
    for row in rows:
        sid = row["share_id"]
        out.setdefault(sid, {
            "share_id": sid, "session_id": row["session_id"], "project_id": row["project_id"],
            "session_name": row["session_name"], "created_at": row["created_at"],
            "revoked_at": row["revoked_at"], "recipients": [],
        })
        out[sid]["recipients"].append({
            "id": row["recipient_id"], "email": row["recipient_email"], "permission": row["permission"],
            "accept_token": row["accept_token"], "accepted_at": row["accepted_at"],
            "revoked_at": row["recipient_revoked_at"], "forked_session_id": row["forked_session_id"],
            "email_sent_at": row["email_sent_at"], "email_error": row["email_error"],
        })
    return list(out.values())


async def list_received_shares(email: str) -> list[dict]:
    logger.info("→ list_received_shares(email=%r)", email)  # autolog
    pool = get_pool()
    e = (email or "").strip().lower()
    if not e:
        return []
    rows = await pool.fetch(
        """
        SELECT r.id AS recipient_id, r.recipient_email, r.permission, r.accept_token,
               r.accepted_at, r.forked_session_id,
               s.id AS share_id, s.session_id, s.project_id, s.created_at, s.owner_user_id,
               sess.title AS session_name, o.name AS owner_name, o.email AS owner_email
        FROM chat_share_recipients r JOIN chat_shares s ON s.id=r.share_id
        LEFT JOIN sessions sess ON sess.id=s.session_id
        LEFT JOIN users o ON o.google_sub=s.owner_user_id
        WHERE lower(r.recipient_email)=$1 AND r.revoked_at IS NULL AND s.revoked_at IS NULL
        ORDER BY s.created_at DESC
        """,
        e,
    )
    return [{
        "recipient_id": row["recipient_id"], "share_id": row["share_id"], "permission": row["permission"],
        "accept_token": row["accept_token"], "accepted_at": row["accepted_at"],
        "forked_session_id": row["forked_session_id"], "session_id": row["session_id"],
        "project_id": row["project_id"], "session_name": row["session_name"],
        "shared_at": row["created_at"], "owner_name": row["owner_name"], "owner_email": row["owner_email"],
    } for row in rows]


async def revoke_share(share_id: str, owner_sub: str) -> bool:
    logger.info("→ revoke_share(share_id=%r owner_sub=%r)", share_id, owner_sub)  # autolog
    pool = get_pool()
    res = await pool.execute(
        "UPDATE chat_shares SET revoked_at=now() WHERE id=$1 AND owner_user_id=$2 AND revoked_at IS NULL",
        share_id, owner_sub,
    )
    return not res.endswith("0")


async def revoke_recipient(recipient_id: str, owner_sub: str) -> bool:
    logger.info("→ revoke_recipient(recipient_id=%r owner_sub=%r)", recipient_id, owner_sub)  # autolog
    pool = get_pool()
    res = await pool.execute(
        "UPDATE chat_share_recipients r SET revoked_at=now() FROM chat_shares s "
        "WHERE r.id=$1 AND r.share_id=s.id AND s.owner_user_id=$2 AND r.revoked_at IS NULL",
        recipient_id, owner_sub,
    )
    return not res.endswith("0")


async def get_recipient_for_owner(recipient_id: str, owner_sub: str) -> dict | None:
    logger.info("→ get_recipient_for_owner(recipient_id=%r owner_sub=%r)", recipient_id, owner_sub)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT r.id AS recipient_id, r.recipient_email, r.permission, r.accept_token,
               sess.title AS session_name
        FROM chat_share_recipients r JOIN chat_shares s ON s.id=r.share_id
        LEFT JOIN sessions sess ON sess.id=s.session_id
        WHERE r.id=$1 AND s.owner_user_id=$2 AND s.revoked_at IS NULL AND r.revoked_at IS NULL
        """,
        recipient_id, owner_sub,
    )
    return dict(row) if row else None


async def mark_email_sent(recipient_id: str) -> None:
    logger.info("→ mark_email_sent(recipient_id=%r)", recipient_id)  # autolog
    pool = get_pool()
    await pool.execute(
        "UPDATE chat_share_recipients SET email_sent_at=now(), email_error=NULL WHERE id=$1",
        recipient_id,
    )


async def mark_email_failed(recipient_id: str, error: str) -> None:
    logger.info("→ mark_email_failed(recipient_id=%r error=%r)", recipient_id, error)  # autolog
    pool = get_pool()
    await pool.execute(
        "UPDATE chat_share_recipients SET email_error=$2, email_sent_at=NULL WHERE id=$1",
        recipient_id, (error or "Unknown")[:500],
    )


async def permission_for_forked_session(session_id: str) -> dict | None:
    """Permission of a forked session (to gate mutations). None if not a fork."""
    logger.info("→ permission_for_forked_session(session_id=%r)", session_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT r.permission, r.revoked_at AS rrev, s.revoked_at AS srev
        FROM sessions sess JOIN chat_share_recipients r ON r.id=sess.share_recipient_id
        JOIN chat_shares s ON s.id=r.share_id
        WHERE sess.id=$1
        """,
        session_id,
    )
    if not row:
        return None
    return {"permission": row["permission"], "revoked": bool(row["rrev"]) or bool(row["srev"])}
