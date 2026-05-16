from __future__ import annotations

from fastapi import APIRouter, Depends, Request

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
