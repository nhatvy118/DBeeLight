from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Request

from internal.repositories.agent_repository import AgentRepository
from internal.repositories.google_oauth_repository import GoogleOAuthRepository
from internal.repositories.project_repository import ProjectRepository
from internal.repositories.user_repository import UserRepository
from internal.usecases.auth_usecase import AuthUseCase
from internal.usecases.chat_usecase import ChatUseCase
from internal.usecases.project_usecase import ProjectUseCase
from internal.usecases.sessions_usecase import SessionsUseCase


@lru_cache
def _agent_repository_singleton() -> AgentRepository:
    # Singleton-ish: AgentRepository keeps the initialized agent + async lock.
    return AgentRepository()


def get_agent_repository(request: Request) -> AgentRepository:
    repo = _agent_repository_singleton()
    repo.set_db_pool(getattr(request.app.state, "db_pool", None))
    return repo


@lru_cache
def get_google_oauth_repository() -> GoogleOAuthRepository:
    return GoogleOAuthRepository()

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
    return ChatUseCase(get_agent_repository(request))


def get_sessions_usecase(request: Request) -> SessionsUseCase:
    return SessionsUseCase(get_agent_repository(request))


def get_user_repository(request: Request) -> UserRepository | None:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return None
    return UserRepository(pool)


def get_auth_usecase(request: Request) -> AuthUseCase:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    return AuthUseCase(get_google_oauth_repository(), get_user_repository(request), frontend_url=frontend_url)

def get_project_repository(request: Request) -> ProjectRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return ProjectRepository(pool)


def get_project_usecase(request: Request) -> ProjectUseCase:
    return ProjectUseCase(get_project_repository(request))