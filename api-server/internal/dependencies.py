from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Request

from internal.repositories.agent_repository import AgentRepository
from internal.repositories.google_oauth_repository import GoogleOAuthRepository
from internal.usecases.auth_usecase import AuthUseCase
from internal.usecases.chat_usecase import ChatUseCase
from internal.usecases.sessions_usecase import SessionsUseCase


@lru_cache
def get_agent_repository() -> AgentRepository:
    # Singleton-ish: AgentRepository keeps the initialized agent + async lock.
    return AgentRepository()


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


def get_chat_usecase() -> ChatUseCase:
    return ChatUseCase(get_agent_repository())


def get_sessions_usecase() -> SessionsUseCase:
    return SessionsUseCase(get_agent_repository())


def get_auth_usecase() -> AuthUseCase:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    return AuthUseCase(get_google_oauth_repository(), frontend_url=frontend_url)

