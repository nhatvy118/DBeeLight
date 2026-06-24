from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.features.auth.deps import get_current_user_id
from app.features.projects import repository as repo
from app.features.projects import service
from app.features.projects.schema import (
    ProjectCreate,
    ProjectOut,
)


router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(p: dict) -> dict:
    return {
        "id": p["id"], "name": p["name"], "description": p.get("description") or "",
    }


def _share_out(s: dict) -> dict:
    return {
        "user_id": s["user_id"], "name": s.get("name"), "email": s.get("email"),
        "role": s.get("role"),
        "shared_at": s["created_at"].isoformat() if s.get("created_at") else None,
    }


@router.post("")
async def create(body: ProjectCreate, user_id: str = Depends(get_current_user_id)) -> dict:
    p = await service.create_project(user_id, body.name, body.description)
    return {"success": True, "project": _to_out(p)}


@router.get("")
async def list_all(user_id: str = Depends(get_current_user_id)) -> dict:
    return {"success": True, "projects": [_to_out(p) for p in await repo.list_projects(user_id)]}


@router.get("/{project_id}", response_model=ProjectOut)
async def get_one(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    # Owner OR shared-with (a viewer must be able to load a project shared with them).
    p = await repo.get_accessible_project(project_id, user_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_out(p)


@router.delete("/{project_id}")
async def remove(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    deleted = await service.delete_project(project_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "deleted_sessions": 0}


# --------------------------------------------------------------------- sharing

@router.get("/shared/with-me")
async def shared_with_me(user_id: str = Depends(get_current_user_id)) -> dict:
    """Projects shared WITH the current user (viewer home)."""
    rows = await service.list_shared_with(user_id)
    projects = [{
        "id": r["id"], "name": r["name"], "description": r.get("description") or "",
        "owner_name": r.get("owner_name"), "owner_email": r.get("owner_email"),
        "shared_at": r["shared_at"].isoformat() if r.get("shared_at") else None,
    } for r in rows]
    return {"success": True, "projects": projects}


@router.get("/{project_id}/shares")
async def list_shares(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    try:
        shares = await service.list_project_shares(project_id, user_id)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"success": True, "shares": [_share_out(s) for s in shares]}


@router.post("/{project_id}/shares")
async def add_share(project_id: str, user_id: str = Depends(get_current_user_id),
                    email: str = Body(..., embed=True)) -> dict:
    try:
        share = await service.share_project(project_id, user_id, email)
    except service.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "share": share}


@router.delete("/{project_id}/shares/{viewer_id}")
async def remove_share(project_id: str, viewer_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    try:
        ok = await service.unshare_project(project_id, user_id, viewer_id)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"success": True}
