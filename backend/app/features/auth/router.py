from __future__ import annotations

from fastapi import APIRouter, Request

from app.features.auth import service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(request: Request, next: str = "/chat"):
    return service.google_login(request, next)


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None):
    return await service.google_callback(request, code, state)


@router.get("/me")
async def me(request: Request):
    return service.me(request)


@router.post("/logout")
async def logout(request: Request):
    return service.logout(request)
