from __future__ import annotations

from fastapi import Depends, Request

from internal.features.admin.repository import AdminRepository
from internal.features.admin.service import AdminService


def get_admin_repository(request: Request) -> AdminRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return AdminRepository(pool)


def get_admin_service(
    repo: AdminRepository = Depends(get_admin_repository),
) -> AdminService:
    return AdminService(repo)
