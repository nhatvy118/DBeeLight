from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.features.admin import repository as repo
from app.features.auth.deps import get_current_user_id

logger = logging.getLogger("features.admin.router")

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _require_admin(request: Request, user_id: str) -> int:
    logger.info("→ _require_admin(request=%r user_id=%r)", request, user_id)  # autolog
    role = await repo.get_user_role(user_id)
    if role is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if role.get("disabled_at") is not None or not role.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return int(role["id"])


def _ser(r: dict) -> dict:
    logger.info("→ _ser(r=%r)", r)  # autolog
    return {
        "id": r["id"], "name": r.get("name"), "email": r.get("email"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "is_admin": bool(r.get("is_admin")), "disabled": r.get("disabled_at") is not None,
        "disabled_at": r["disabled_at"].isoformat() if r.get("disabled_at") else None,
        "project_count": int(r.get("project_count") or 0),
        "session_count": int(r.get("session_count") or 0),
        "storage_bytes": int(r.get("storage_bytes") or 0),
    }


@router.get("/users")
async def list_users(request: Request, user_id: str = Depends(get_current_user_id)):
    logger.info("→ list_users(request=%r user_id=%r)", request, user_id)  # autolog
    await _require_admin(request, user_id)
    rows = await repo.list_users_with_stats()
    return {"success": True, "users": [_ser(r) for r in rows]}


@router.get("/stats")
async def get_stats(request: Request, user_id: str = Depends(get_current_user_id)):
    logger.info("→ get_stats(request=%r user_id=%r)", request, user_id)  # autolog
    await _require_admin(request, user_id)
    s = await repo.get_overview_stats()
    return {"success": True, "stats": {k: int(v or 0) for k, v in s.items()}}


@router.post("/users/{target_id}/disable")
async def disable_user(target_id: int, request: Request, user_id: str = Depends(get_current_user_id)):
    logger.info("→ disable_user(target_id=%r request=%r user_id=%r)", target_id, request, user_id)  # autolog
    admin_id = await _require_admin(request, user_id)
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    updated = await repo.set_user_disabled(target_id, True)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "id": updated["id"], "disabled": updated["disabled_at"] is not None}


@router.post("/users/{target_id}/enable")
async def enable_user(target_id: int, request: Request, user_id: str = Depends(get_current_user_id)):
    logger.info("→ enable_user(target_id=%r request=%r user_id=%r)", target_id, request, user_id)  # autolog
    await _require_admin(request, user_id)
    updated = await repo.set_user_disabled(target_id, False)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "id": updated["id"], "disabled": updated["disabled_at"] is not None}
