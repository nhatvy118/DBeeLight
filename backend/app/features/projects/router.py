from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.features.auth.deps import get_current_user_id
from app.features.projects import repository as repo
from app.features.projects import service
from app.features.projects.schema import (
    ConnectPostgres,
    ConnectResult,
    ProjectCreate,
    ProjectOut,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(p: dict) -> dict:
    return {
        "id": p["id"], "name": p["name"], "description": p.get("description") or "",
        "has_db": service.is_configured(p.get("db_url")),
    }


@router.post("")
async def create(body: ProjectCreate, user_id: str = Depends(get_current_user_id)) -> dict:
    p = await repo.create_project(user_id, body.name, body.description)
    return {"success": True, "project": _to_out(p)}


@router.get("")
async def list_all(user_id: str = Depends(get_current_user_id)) -> dict:
    return {"success": True, "projects": [_to_out(p) for p in await repo.list_projects(user_id)]}


@router.get("/{project_id}", response_model=ProjectOut)
async def get_one(project_id: str, user_id: str = Depends(get_current_user_id)) -> ProjectOut:
    p = await repo.get_project(project_id, user_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_out(p)


@router.delete("/{project_id}")
async def remove(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    deleted = await repo.delete_project(project_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "deleted_sessions": 0}


@router.post("/{project_id}/connect/postgres", response_model=ConnectResult)
async def connect_pg(
    project_id: str, body: ConnectPostgres, user_id: str = Depends(get_current_user_id)
) -> ConnectResult:
    if not await repo.get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Project not found")
    ok, info = await service.connect_postgres(
        project_id, user_id, body.host, body.port, body.database, body.username, body.password
    )
    if not ok:
        return ConnectResult(status="error", detail=info)
    return ConnectResult(status="ok", engine=info)


@router.post("/{project_id}/connect/sqlite", response_model=ConnectResult)
async def connect_sqlite(project_id: str, user_id: str = Depends(get_current_user_id)) -> ConnectResult:
    if not await repo.get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Project not found")
    ok, info = await service.connect_sqlite(project_id, user_id)
    if not ok:
        return ConnectResult(status="error", detail=info)
    return ConnectResult(status="ok", engine=info)
