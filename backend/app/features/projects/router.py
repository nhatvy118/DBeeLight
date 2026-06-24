from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.features.auth.deps import get_current_user_id
from app.features.projects import repository as repo
from app.features.projects import service
from app.features.projects.schema import (
    ExternalConnection,
    ExternalProjectCreate,
    ProjectCreate,
    ProjectOut,
)


router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(p: dict) -> dict:
    return {
        "id": p["id"], "name": p["name"], "description": p.get("description") or "",
        "kind": p.get("kind") or "internal",
    }


def _share_out(s: dict) -> dict:
    return {
        "user_id": s["user_id"], "name": s.get("name"), "email": s.get("email"),
        "role": s.get("role"), "permission": s.get("permission") or "view",
        "shared_at": s["created_at"].isoformat() if s.get("created_at") else None,
    }


@router.post("")
async def create(body: ProjectCreate, user_id: str = Depends(get_current_user_id)) -> dict:
    p = await service.create_project(user_id, body.name, body.description)
    return {"success": True, "project": _to_out(p)}


@router.post("/external/test")
async def test_external(body: ExternalConnection, user_id: str = Depends(get_current_user_id)) -> dict:
    """Probe a connection without creating anything (the 'Test connection' button)."""
    dsn = service.build_dsn(body.host, body.port, body.database, body.username, body.password)
    try:
        await service.probe_connection(dsn)
    except service.ProjectError as e:
        return {"success": False, "message": str(e)}
    return {"success": True, "message": "Connected"}


@router.post("/external")
async def create_external(body: ExternalProjectCreate, user_id: str = Depends(get_current_user_id)) -> dict:
    """Create a project bound to the user's own external Postgres database."""
    dsn = service.build_dsn(body.host, body.port, body.database, body.username, body.password)
    try:
        p = await service.create_external_project(user_id, body.name, dsn, body.description)
    except service.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "project": _to_out(p)}


@router.get("/{project_id}/connection")
async def get_connection(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    """Return the external project's connection fields (incl. password) for the OWNER to review."""
    try:
        info = await service.get_connection_info(project_id, user_id)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"success": True, "connection": info}


@router.put("/{project_id}/connection")
async def update_connection(project_id: str, body: ExternalConnection,
                            user_id: str = Depends(get_current_user_id)) -> dict:
    """Re-point an external project at a new DSN (Edit connection). Owner-only."""
    dsn = service.build_dsn(body.host, body.port, body.database, body.username, body.password)
    try:
        await service.update_project_connection(project_id, user_id, dsn)
    except service.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "message": "Connected"}


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


@router.get("/{project_id}/shareable")
async def shareable_users(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    """Active users this project can still be shared with (pick-list for the share modal)."""
    try:
        users = await service.list_shareable(project_id, user_id)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"success": True, "users": [
        {"user_id": u["user_id"], "name": u.get("name"), "email": u.get("email"), "role": u.get("role")}
        for u in users
    ]}


@router.get("/{project_id}/shares")
async def list_shares(project_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    try:
        shares = await service.list_project_shares(project_id, user_id)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"success": True, "shares": [_share_out(s) for s in shares]}


@router.post("/{project_id}/shares")
async def add_share(project_id: str, user_id: str = Depends(get_current_user_id),
                    email: str = Body(..., embed=True), permission: str = Body("view", embed=True)) -> dict:
    if permission not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="Invalid permission")
    try:
        share = await service.share_project(project_id, user_id, email, permission)
    except service.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "share": share}


@router.post("/{project_id}/shares/{viewer_id}/permission")
async def set_share_permission(project_id: str, viewer_id: str, user_id: str = Depends(get_current_user_id),
                               permission: str = Body(..., embed=True)) -> dict:
    if permission not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="Invalid permission")
    try:
        perm = await service.set_share_permission(project_id, user_id, viewer_id, permission)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"success": True, "permission": perm}


@router.delete("/{project_id}/shares/{viewer_id}")
async def remove_share(project_id: str, viewer_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    try:
        ok = await service.unshare_project(project_id, user_id, viewer_id)
    except service.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"success": True}
