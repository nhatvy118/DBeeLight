from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from internal.dependencies import get_auth_usecase
from internal.usecases.auth_usecase import AuthUseCase


router = APIRouter()

@router.get("/api/auth/google/login")
async def google_login(request: Request, next: str = "/chat", usecase: AuthUseCase = Depends(get_auth_usecase)):
    return usecase.google_login(request, next)

@router.get("/api/auth/google/callback", name="google_callback")
async def google_callback(
    request: Request, code: str | None = None, state: str | None = None, usecase: AuthUseCase = Depends(get_auth_usecase)
):
    return usecase.google_callback(request, code, state)

@router.get("/api/auth/me")
async def auth_me(request: Request, usecase: AuthUseCase = Depends(get_auth_usecase)):
    return usecase.me(request)

@router.post("/api/auth/logout")
async def auth_logout(request: Request, usecase: AuthUseCase = Depends(get_auth_usecase)):
    return usecase.logout(request)

