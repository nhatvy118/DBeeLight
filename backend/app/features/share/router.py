from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.features.auth.deps import get_current_user_id
from app.features.share import service
from app.features.share.schema import CreateShareRequest

router = APIRouter(tags=["shares"])


def _email(request: Request) -> str | None:
    u = request.session.get("user") or {}
    return u.get("email") if isinstance(u, dict) else None


def _name(request: Request) -> str | None:
    u = request.session.get("user") or {}
    return u.get("name") if isinstance(u, dict) else None


@router.post("/api/sessions/{session_id}/share")
async def create_share(session_id: str, body: CreateShareRequest, request: Request,
                       user_id: str = Depends(get_current_user_id)):
    return await service.create_share(
        owner_sub=user_id, owner_name=_name(request), owner_email=_email(request),
        session_id=session_id, recipients=[r.model_dump() for r in body.recipients],
        notify_via_email=body.notify_via_email,
    )


@router.get("/api/shares/sent")
async def list_sent(user_id: str = Depends(get_current_user_id)):
    return await service.list_sent(user_id)


@router.get("/api/shares/received")
async def list_received(request: Request, user_id: str = Depends(get_current_user_id)):
    return await service.list_received(_email(request))


@router.get("/api/shares/by-token/{accept_token}")
async def preview_share(accept_token: str, user_id: str = Depends(get_current_user_id)):
    return await service.preview(accept_token)


@router.post("/api/shares/{accept_token}/accept")
async def accept_share(accept_token: str, request: Request, user_id: str = Depends(get_current_user_id)):
    return await service.accept(accept_token, user_id, _email(request))


@router.delete("/api/shares/{share_id}")
async def revoke_share(share_id: str, user_id: str = Depends(get_current_user_id)):
    return await service.revoke_share(share_id, user_id)


@router.post("/api/shares/recipients/{recipient_id}/resend-email")
async def resend_email(recipient_id: str, request: Request, user_id: str = Depends(get_current_user_id)):
    return await service.resend_email(recipient_id, user_id, _name(request))


@router.delete("/api/shares/recipients/{recipient_id}")
async def revoke_recipient(recipient_id: str, user_id: str = Depends(get_current_user_id)):
    return await service.revoke_recipient(recipient_id, user_id)
