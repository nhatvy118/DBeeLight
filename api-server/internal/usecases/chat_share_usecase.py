from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import HTTPException

from internal.repositories.chat_share_repository import (
    VALID_PERMISSIONS,
    ChatShareRepository,
)
from internal.services.email_service import EmailService

logger = logging.getLogger(__name__)


class ChatShareUseCase:
    """Business logic for sharing chat sessions across users."""

    def __init__(
        self,
        share_repo: ChatShareRepository,
        email_service: Optional[EmailService] = None,
    ):
        self._repo = share_repo
        self._email = email_service

    async def create_share(
        self,
        *,
        owner_google_sub: str,
        owner_name: str | None,
        session_id: str,
        recipients: list[dict[str, str]],
        owner_email: str | None,
        frontend_url: str,
        notify_via_email: bool = True,
    ) -> dict[str, Any]:
        if owner_google_sub == "anonymous":
            raise HTTPException(status_code=401, detail="Login required to share")
        if not (session_id or "").strip():
            raise HTTPException(status_code=400, detail="session_id is required")
        if not recipients:
            raise HTTPException(status_code=400, detail="At least one recipient is required")

        # Normalize + validate recipients early so we don't open a transaction we'll abort.
        norm: list[dict[str, str]] = []
        seen_emails: set[str] = set()
        for r in recipients:
            email = (r.get("email") or "").strip().lower()
            perm = (r.get("permission") or "").strip()
            if not email:
                raise HTTPException(status_code=400, detail="Each recipient must have an email")
            if perm not in VALID_PERMISSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid permission {perm!r}; must be one of {sorted(VALID_PERMISSIONS)}",
                )
            if owner_email and email == (owner_email or "").lower():
                raise HTTPException(status_code=400, detail="Cannot share to yourself")
            if email in seen_emails:
                raise HTTPException(status_code=400, detail=f"Duplicate recipient email: {email}")
            seen_emails.add(email)
            norm.append({"email": email, "permission": perm})

        # Verify session ownership (and that it's not itself a forked session).
        session_row = await self._repo.verify_session_owner(
            session_id=session_id, owner_google_sub=owner_google_sub
        )
        if session_row is None:
            raise HTTPException(
                status_code=403,
                detail="Session not found or you don't own it (forked sessions cannot be re-shared)",
            )

        project_id = session_row["project_id"]
        if project_id is None:
            raise HTTPException(
                status_code=400,
                detail="Only sessions attached to a project can be shared",
            )

        try:
            share = await self._repo.create_share(
                owner_user_id=owner_google_sub,
                session_id=session_id,
                project_id=str(project_id),
                recipients=norm,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # Build per-recipient accept URLs.
        base = (frontend_url or "").rstrip("/") or "http://localhost:5173"
        for r in share["recipients"]:
            r["accept_url"] = f"{base}/share/accept/{r['accept_token']}"

        # Fire-and-forget email notifications. Failures are recorded on the
        # recipient row (``email_error``) but do NOT fail the share itself —
        # the user can still copy the link manually, and we expose a "Resend"
        # button in the UI.
        session_name = (session_row.get("session_name") or "").strip() or None
        if (
            notify_via_email
            and self._email is not None
            and share["recipients"]
        ):
            asyncio.create_task(
                self._send_share_emails_bg(
                    recipients=share["recipients"],
                    owner_name=(owner_name or owner_email or "Someone"),
                    owner_email=owner_email,
                    session_name=session_name,
                )
            )

        return share

    async def _send_share_emails_bg(
        self,
        *,
        recipients: list[dict[str, Any]],
        owner_name: str,
        owner_email: str | None,
        session_name: str | None,
    ) -> None:
        """Background task: send a notification email per recipient and mark
        the row as sent or failed. Errors are caught per-recipient so a
        single bad address doesn't block the others."""
        if self._email is None:
            return
        for r in recipients:
            try:
                await self._email.send_share_notification(
                    to_email=r["email"],
                    owner_name=owner_name,
                    owner_email=owner_email,
                    session_name=session_name,
                    permission=r["permission"],
                    accept_token=r["accept_token"],
                )
                await self._repo.mark_email_sent(r["id"])
            except Exception as e:
                logger.exception(f"Failed to send share email to {r.get('email')}")
                try:
                    await self._repo.mark_email_failed(r["id"], str(e))
                except Exception:
                    logger.exception("And failed to record the email error")

    async def list_sent(self, owner_google_sub: str) -> list[dict[str, Any]]:
        if owner_google_sub == "anonymous":
            raise HTTPException(status_code=401, detail="Login required")
        return await self._repo.list_sent_shares(owner_google_sub)

    async def list_received(
        self, *, recipient_email: str | None, recipient_google_sub: str
    ) -> list[dict[str, Any]]:
        if recipient_google_sub == "anonymous" or not recipient_email:
            raise HTTPException(status_code=401, detail="Login required")
        return await self._repo.list_received_shares(
            recipient_email=recipient_email, recipient_google_sub=recipient_google_sub
        )

    async def accept_share(
        self,
        *,
        accept_token: str,
        recipient_google_sub: str,
        recipient_email: str | None,
    ) -> dict[str, Any]:
        if recipient_google_sub == "anonymous" or not recipient_email:
            raise HTTPException(status_code=401, detail="Login required to accept share")

        rec = await self._repo.get_recipient_by_token(accept_token)
        if rec is None:
            raise HTTPException(status_code=404, detail="Share link not found")
        if rec["revoked_at"] is not None or rec["share_revoked_at"] is not None:
            raise HTTPException(status_code=410, detail="This share has been revoked")
        if (rec["recipient_email"] or "").lower() != recipient_email.lower():
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This share was sent to {rec['recipient_email']}. "
                    f"Log in with that account to access it."
                ),
            )

        try:
            forked = await self._repo.fork_session_for_recipient(
                recipient_id=str(rec["recipient_id"]),
                recipient_google_sub=recipient_google_sub,
                recipient_email=recipient_email,
            )
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        return {
            "session_id": forked["session_id"],
            "project_id": forked["project_id"],
            "permission": forked["permission"],
            "owner_name": None,  # filled by controller if needed
            "already_accepted": forked.get("already_accepted", False),
        }

    async def resend_email(
        self,
        *,
        recipient_id: str,
        owner_google_sub: str,
        owner_name: str | None,
        owner_email: str | None,
    ) -> dict[str, Any]:
        """Manually retry sending the notification email for one recipient.

        Owner-only. Surfaces the success/error inline so the UI can update
        the email-status chip without a second list call.
        """
        if owner_google_sub == "anonymous":
            raise HTTPException(status_code=401, detail="Login required")
        if self._email is None:
            raise HTTPException(
                status_code=503,
                detail="Email service is not configured (RESEND_API_KEY missing)",
            )

        rec = await self._repo.get_recipient_for_owner(
            recipient_id=recipient_id, owner_google_sub=owner_google_sub
        )
        if rec is None:
            raise HTTPException(
                status_code=404,
                detail="Recipient not found, revoked, or not owned by you",
            )

        try:
            await self._email.send_share_notification(
                to_email=rec["recipient_email"],
                owner_name=(owner_name or owner_email or "Someone"),
                owner_email=owner_email,
                session_name=rec.get("session_name"),
                permission=rec["permission"],
                accept_token=rec["accept_token"],
            )
            await self._repo.mark_email_sent(str(rec["recipient_id"]))
            return {"status": "sent"}
        except Exception as e:
            logger.exception(f"Resend email to {rec['recipient_email']} failed")
            await self._repo.mark_email_failed(str(rec["recipient_id"]), str(e))
            raise HTTPException(
                status_code=502,
                detail=f"Failed to send email: {e}",
            ) from e

    async def revoke_share(self, *, share_id: str, owner_google_sub: str) -> bool:
        if owner_google_sub == "anonymous":
            raise HTTPException(status_code=401, detail="Login required")
        ok = await self._repo.revoke_share(share_id=share_id, owner_google_sub=owner_google_sub)
        if not ok:
            raise HTTPException(status_code=404, detail="Share not found or not owned by you")
        return True

    async def revoke_recipient(self, *, recipient_id: str, owner_google_sub: str) -> bool:
        if owner_google_sub == "anonymous":
            raise HTTPException(status_code=401, detail="Login required")
        ok = await self._repo.revoke_recipient(
            recipient_id=recipient_id, owner_google_sub=owner_google_sub
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Recipient not found or not owned by you")
        return True
