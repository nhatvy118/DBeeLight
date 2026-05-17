from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Request

from internal.features.share.repository import ChatShareRepository
from internal.features.share.service import ChatShareService
from internal.features.share.email_service import EmailService


def get_chat_share_repository(request: Request) -> ChatShareRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return ChatShareRepository(pool)


@lru_cache
def _email_service_singleton() -> EmailService | None:
    """One EmailService for the process. ``None`` when RESEND_API_KEY isn't
    set — share endpoints handle that gracefully."""
    return EmailService.from_env()


def get_chat_share_service(
    repo: ChatShareRepository = Depends(get_chat_share_repository),
) -> ChatShareService:
    return ChatShareService(repo, email_service=_email_service_singleton())
