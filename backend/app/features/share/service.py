"""Chat sharing business logic (full)."""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from app.features.share import email_service
from app.features.share import repository as repo

logger = logging.getLogger("share")

# view_only < read_data < edit_data
RANK = {"view_only": 0, "read_data": 1, "edit_data": 2}


def allows(granted: str, required: str | None) -> bool:
    logger.info("→ allows(granted=%r required=%r)", granted, required)  # autolog
    return RANK.get(granted, -1) >= RANK.get(required or "read_data", 99)


async def create_share(*, owner_sub: str, owner_name: str | None, owner_email: str | None,
                       session_id: str, recipients: list[dict], notify_via_email: bool) -> dict:
    logger.info("→ create_share(owner_sub=%r owner_name=%r owner_email=%r session_id=%r recipients=%r notify_via_email=%r)", owner_sub, owner_name, owner_email, session_id, recipients, notify_via_email)  # autolog
    if not recipients:
        raise HTTPException(status_code=400, detail="At least one recipient is required")
    norm, seen = [], set()
    for r in recipients:
        email = (r.get("email") or "").strip().lower()
        perm = (r.get("permission") or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail="Recipient is missing an email")
        if perm not in repo.VALID_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"Invalid permission: {perm}")
        if owner_email and email == owner_email.lower():
            raise HTTPException(status_code=400, detail="Cannot share to yourself")
        if email in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate email: {email}")
        seen.add(email)
        norm.append({"email": email, "permission": perm})

    sess = await repo.verify_session_owner(session_id, owner_sub)
    if sess is None:
        raise HTTPException(status_code=403, detail="Session is not yours (or is a forked session)")

    share = await repo.create_share(owner_sub, session_id, sess["project_id"], norm)

    if notify_via_email and email_service.is_configured():
        asyncio.create_task(_send_emails_bg(share["recipients"], owner_name or owner_email or "Someone",
                                            sess.get("title")))
    else:
        for r in share["recipients"]:
            await repo.mark_email_failed(r["id"], "Email not enabled (RESEND_API_KEY)")
    return {"success": True, **share}


async def _send_emails_bg(recipients: list[dict], owner_name: str, session_name: str | None) -> None:
    logger.info("→ _send_emails_bg(recipients=%r owner_name=%r session_name=%r)", recipients, owner_name, session_name)  # autolog
    for r in recipients:
        try:
            await email_service.send_share_notification(
                to_email=r["email"], owner_name=owner_name, session_name=session_name,
                permission=r["permission"], accept_token=r["accept_token"],
            )
            await repo.mark_email_sent(r["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to send share email %s: %s", r.get("email"), e)
            await repo.mark_email_failed(r["id"], str(e))


async def list_sent(owner_sub: str) -> dict:
    logger.info("→ list_sent(owner_sub=%r)", owner_sub)  # autolog
    return {"success": True, "shares": await repo.list_sent_shares(owner_sub)}


async def list_received(email: str | None) -> dict:
    logger.info("→ list_received(email=%r)", email)  # autolog
    if not email:
        raise HTTPException(status_code=401, detail="Login required")
    return {"success": True, "shares": await repo.list_received_shares(email)}


async def preview(token: str) -> dict:
    logger.info("→ preview(token=***)")  # autolog
    rec = await repo.get_recipient_by_token(token)
    if rec is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    if rec["revoked_at"] is not None or rec["share_revoked_at"] is not None:
        raise HTTPException(status_code=410, detail="Share has been revoked")
    return {"success": True, "share": {
        "session_name": rec["session_name"], "permission": rec["permission"],
        "recipient_email": rec["recipient_email"], "already_accepted": rec["accepted_at"] is not None,
    }}


async def accept(token: str, recipient_sub: str, recipient_email: str | None) -> dict:
    logger.info("→ accept(token=*** recipient_sub=%r recipient_email=%r)", recipient_sub, recipient_email)  # autolog
    if not recipient_email:
        raise HTTPException(status_code=401, detail="Login required")
    rec = await repo.get_recipient_by_token(token)
    if rec is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    if rec["revoked_at"] is not None or rec["share_revoked_at"] is not None:
        raise HTTPException(status_code=410, detail="Share has been revoked")
    if (rec["recipient_email"] or "").lower() != recipient_email.lower():
        raise HTTPException(status_code=403,
                            detail=f"This share was sent to {rec['recipient_email']}. Log in with that account.")
    try:
        forked = await repo.fork_session_for_recipient(rec["recipient_id"], recipient_sub, recipient_email)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"success": True, **forked}


async def revoke_share(share_id: str, owner_sub: str) -> dict:
    logger.info("→ revoke_share(share_id=%r owner_sub=%r)", share_id, owner_sub)  # autolog
    ok = await repo.revoke_share(share_id, owner_sub)
    if not ok:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"success": True}


async def revoke_recipient(recipient_id: str, owner_sub: str) -> dict:
    logger.info("→ revoke_recipient(recipient_id=%r owner_sub=%r)", recipient_id, owner_sub)  # autolog
    ok = await repo.revoke_recipient(recipient_id, owner_sub)
    if not ok:
        raise HTTPException(status_code=404, detail="Recipient not found")
    return {"success": True}


async def resend_email(recipient_id: str, owner_sub: str, owner_name: str | None) -> dict:
    logger.info("→ resend_email(recipient_id=%r owner_sub=%r owner_name=%r)", recipient_id, owner_sub, owner_name)  # autolog
    rec = await repo.get_recipient_for_owner(recipient_id, owner_sub)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if not email_service.is_configured():
        await repo.mark_email_failed(recipient_id, "Email not enabled (RESEND_API_KEY)")
        raise HTTPException(status_code=400, detail="Email not configured")
    try:
        await email_service.send_share_notification(
            to_email=rec["recipient_email"], owner_name=owner_name or "Someone",
            session_name=rec.get("session_name"), permission=rec["permission"],
            accept_token=rec["accept_token"],
        )
        await repo.mark_email_sent(recipient_id)
    except Exception as e:  # noqa: BLE001
        await repo.mark_email_failed(recipient_id, str(e))
        raise HTTPException(status_code=502, detail=f"Failed to send email: {e}") from e
    return {"success": True}
