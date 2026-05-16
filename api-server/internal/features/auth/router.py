from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from internal.features.auth.dependencies import get_auth_service
from internal.features.auth.service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(
    request: Request,
    next: str = "/chat",
    service: AuthService = Depends(get_auth_service),
):
    return service.google_login(request, next)


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    service: AuthService = Depends(get_auth_service),
):
    return await service.google_callback(request, code, state)


@router.get("/me")
async def auth_me(request: Request, service: AuthService = Depends(get_auth_service)):
    return service.me(request)


@router.post("/logout")
async def auth_logout(request: Request, service: AuthService = Depends(get_auth_service)):
    return service.logout(request)
