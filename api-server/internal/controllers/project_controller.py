from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from internal.controllers.schemas import CreateProjectRequest
from internal.dependencies import get_project_repository, get_project_usecase
from internal.usecases.project_usecase import ProjectUseCase


router = APIRouter()


@router.post("/api/projects")
async def create_project(
    req: CreateProjectRequest,
    request: Request,
    usecase: ProjectUseCase = Depends(get_project_usecase),
):
    return await usecase.create_project(request, req.name, req.description, req.db_url or '')


@router.get("/api/projects")
async def list_projects(
    request: Request,
    usecase: ProjectUseCase = Depends(get_project_usecase),
):
    return await usecase.list_projects(request)
