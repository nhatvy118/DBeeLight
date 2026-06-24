from __future__ import annotations
import logging

from fastapi import APIRouter, Request

from app.features.auth import service

logger = logging.getLogger("features.auth.router")

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(request: Request, next: str = "/chat"):
    logger.info("→ google_login(request=%r next=%r)", request, next)  # autolog
    return service.google_login(request, next)


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None):
    logger.info("→ google_callback(request=%r code=%r state=%r)", request, code, state)  # autolog
    return await service.google_callback(request, code, state)


@router.get("/me")
async def me(request: Request):
    logger.info("→ me(request=%r)", request)  # autolog
    return service.me(request)


@router.post("/logout")
async def logout(request: Request):
    logger.info("→ logout(request=%r)", request)  # autolog
    return service.logout(request)
