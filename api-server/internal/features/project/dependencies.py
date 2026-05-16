from __future__ import annotations

from fastapi import Depends, Request

from internal.features.project.repository import ProjectRepository
from internal.features.project.service import ProjectService


def get_project_repository(request: Request) -> ProjectRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return ProjectRepository(pool)


def get_project_service(
    repo: ProjectRepository = Depends(get_project_repository),
) -> ProjectService:
    return ProjectService(repo)
