from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from internal.features.auth.dependencies import (
    get_auth_service as get_auth_service,
    get_google_oauth_repository as get_google_oauth_repository,
    get_user_repository as get_user_repository,
)
from internal.features.project.dependencies import (
    get_project_repository as get_project_repository,
    get_project_service as get_project_service,
)
from internal.features.project.repository import ProjectRepository
from internal.features.sessions.dependencies import (
    get_sessions_service as get_sessions_service,
)
from internal.repositories.agent_repository import AgentRepository
from internal.repositories.chat_share_repository import ChatShareRepository
from internal.services.email_service import EmailService
from internal.usecases.chat_share_usecase import ChatShareUseCase
from internal.usecases.chat_usecase import ChatUseCase
from internal.usecases.file_usecase import FileUseCase
from internal.utils.redis_client import get_redis_client


@lru_cache
def _agent_repository_singleton() -> AgentRepository:
    # Singleton-ish: AgentRepository keeps the initialized agent + async lock.
    return AgentRepository()


def get_agent_repository(request: Request) -> AgentRepository:
    repo = _agent_repository_singleton()
    repo.set_db_pool(getattr(request.app.state, "db_pool", None))
    return repo


def get_user_key(request: Request) -> str:
    """
    Return a stable per-user key for chat history isolation.
    - Logged-in users: Google "sub"
    - Otherwise: "anonymous"
    """
    user = request.session.get("user") if hasattr(request, "session") else None
    if isinstance(user, dict):
        sub = user.get("sub")
        if isinstance(sub, str) and sub.strip():
            return sub.strip()
    return "anonymous"


def get_chat_usecase(request: Request) -> ChatUseCase:
    pool = getattr(request.app.state, "db_pool", None)
    project_repo = ProjectRepository(pool) if pool else None
    share_repo = ChatShareRepository(pool) if pool else None
    file_uc = FileUseCase(pool, project_repo) if pool else None
    return ChatUseCase(get_agent_repository(request), project_repo, share_repo, file_uc)


def get_file_usecase(request: Request) -> FileUseCase:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return FileUseCase(pool, ProjectRepository(pool))


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


def get_chat_share_usecase(request: Request) -> ChatShareUseCase:
    return ChatShareUseCase(
        get_chat_share_repository(request),
        email_service=_email_service_singleton(),
    )


async def get_redis_client_dependency() -> object:
    """
    Dependency function to get Redis client.
    Returns Redis client or None if not available.
    """
    return await get_redis_client()
