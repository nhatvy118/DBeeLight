from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from internal.features.admin.dependencies import get_admin_service
from internal.features.admin.service import AdminService

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    request: Request,
    service: AdminService = Depends(get_admin_service),
):
    """List all users with per-user stats (admin only)."""
    return await service.list_users(request)


@router.get("/stats")
async def get_stats(
    request: Request,
    service: AdminService = Depends(get_admin_service),
):
    """Platform overview counts (admin only)."""
    return await service.get_stats(request)


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: int,
    request: Request,
    service: AdminService = Depends(get_admin_service),
):
    """Disable a user account — they can no longer sign in (admin only)."""
    return await service.set_disabled(request, user_id, True)


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: int,
    request: Request,
    service: AdminService = Depends(get_admin_service),
):
    """Re-enable a disabled user account (admin only)."""
    return await service.set_disabled(request, user_id, False)
