from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from internal.controllers.schemas import CreateShareRequest
from internal.dependencies import get_chat_share_usecase, get_user_key
from internal.usecases.chat_share_usecase import ChatShareUseCase

logger = logging.getLogger(__name__)
router = APIRouter()


def _user_email(request: Request) -> str | None:
    user = request.session.get("user") if hasattr(request, "session") else None
    if isinstance(user, dict):
        email = user.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return None


def _user_name(request: Request) -> str | None:
    user = request.session.get("user") if hasattr(request, "session") else None
    if isinstance(user, dict):
        name = user.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _frontend_url(request: Request) -> str:
    env = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if env:
        return env
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    return "http://localhost:5173"


@router.post("/api/sessions/{session_id}/share")
async def create_share(
    session_id: str,
    body: CreateShareRequest,
    request: Request,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    """Owner shares a chat session with one or more recipients."""
    # Allow body.session_id to be empty; URL path is authoritative.
    sid = (session_id or body.session_id or "").strip()
    result = await usecase.create_share(
        owner_google_sub=user_key,
        owner_name=_user_name(request),
        session_id=sid,
        recipients=[r.model_dump() for r in body.recipients],
        owner_email=_user_email(request),
        frontend_url=_frontend_url(request),
        notify_via_email=body.notify_via_email,
    )
    return {"success": True, **result}


@router.get("/api/shares/sent")
async def list_sent(
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    shares = await usecase.list_sent(owner_google_sub=user_key)
    return {"success": True, "shares": shares}


@router.get("/api/shares/received")
async def list_received(
    request: Request,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    shares = await usecase.list_received(
        recipient_email=_user_email(request),
        recipient_google_sub=user_key,
    )
    return {"success": True, "shares": shares}


@router.get("/api/shares/by-token/{accept_token}")
async def preview_share(
    accept_token: str,
    request: Request,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    """Lightweight preview for the accept page (does not fork)."""
    rec = await usecase._repo.get_recipient_by_token(accept_token)
    if rec is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    if rec["revoked_at"] is not None or rec["share_revoked_at"] is not None:
        raise HTTPException(status_code=410, detail="This share has been revoked")
    user_email = _user_email(request)
    email_match = (
        bool(user_email)
        and (rec["recipient_email"] or "").lower() == user_email.lower()
    )
    return {
        "success": True,
        "share": {
            "recipient_email": rec["recipient_email"],
            "permission": rec["permission"],
            "session_name": rec["session_name"],
            "accepted_at": rec["accepted_at"],
            "forked_session_id": rec["forked_session_id"],
            "project_id": str(rec["project_id"]),
            "logged_in": user_key != "anonymous",
            "email_match": email_match,
        },
    }


@router.post("/api/shares/{accept_token}/accept")
async def accept_share(
    accept_token: str,
    request: Request,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    """Recipient accepts a share — snapshot-forks the session and returns the new session_id."""
    result = await usecase.accept_share(
        accept_token=accept_token,
        recipient_google_sub=user_key,
        recipient_email=_user_email(request),
    )
    return {"success": True, **result}


@router.delete("/api/shares/{share_id}")
async def revoke_share(
    share_id: str,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    await usecase.revoke_share(share_id=share_id, owner_google_sub=user_key)
    return {"success": True}


@router.post("/api/shares/recipients/{recipient_id}/resend-email")
async def resend_share_email(
    recipient_id: str,
    request: Request,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    """Owner re-sends the notification email for a single recipient."""
    result = await usecase.resend_email(
        recipient_id=recipient_id,
        owner_google_sub=user_key,
        owner_name=_user_name(request),
        owner_email=_user_email(request),
    )
    return {"success": True, **result}


@router.delete("/api/shares/recipients/{recipient_id}")
async def revoke_recipient(
    recipient_id: str,
    user_key: str = Depends(get_user_key),
    usecase: ChatShareUseCase = Depends(get_chat_share_usecase),
):
    await usecase.revoke_recipient(recipient_id=recipient_id, owner_google_sub=user_key)
    return {"success": True}
