from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from internal.features.file.dependencies import get_file_service
from internal.features.file.service import FileService
from internal.features.project.dependencies import get_project_service
from internal.features.project.schema import CreateProjectRequest
from internal.features.project.service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("")
async def create_project(
    body: CreateProjectRequest,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    return await service.create_project(request, body.name, body.description, body.db_url or "")


@router.get("")
async def list_projects(
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    return await service.list_projects(request)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
    file_service: FileService = Depends(get_file_service),
):
    """Delete a project plus its chat sessions, uploaded files, temp DBs, and SQLite database file."""
    return await service.delete_project(request, project_id, file_service)
