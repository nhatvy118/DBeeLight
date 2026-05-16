from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Depends, Request

from internal.features.auth.google_oauth import GoogleOAuthRepository
from internal.features.auth.repository import UserRepository
from internal.features.auth.service import AuthService


@lru_cache
def get_google_oauth_repository() -> GoogleOAuthRepository:
    return GoogleOAuthRepository()


def get_user_repository(request: Request) -> UserRepository | None:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return None
    return UserRepository(pool)


def get_auth_service(
    request: Request,
    google_repo: GoogleOAuthRepository = Depends(get_google_oauth_repository),
    user_repo: UserRepository | None = Depends(get_user_repository),
) -> AuthService:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    return AuthService(google_repo, user_repo, frontend_url=frontend_url)
