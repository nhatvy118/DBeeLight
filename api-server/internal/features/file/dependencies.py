from __future__ import annotations

from fastapi import Depends, Request

from internal.features.file.repository import FileRepository
from internal.features.file.service import FileService
from internal.features.project.dependencies import get_project_repository
from internal.features.project.repository import ProjectRepository


def get_file_repository(request: Request) -> FileRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return FileRepository(pool)


def get_file_service(
    request: Request,
    project_repo: ProjectRepository = Depends(get_project_repository),
) -> FileService:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return FileService(pool, project_repo)
