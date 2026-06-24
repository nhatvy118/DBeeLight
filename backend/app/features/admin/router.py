from __future__ import annotations
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.features.admin import repository as repo
from app.features.auth.deps import get_current_user_id

logger = logging.getLogger("features.admin.router")

router = APIRouter(prefix="/api/admin", tags=["admin"])

_ROLES = set(repo.ROLES)


async def _require_admin(user_id: str) -> int:
    """Gate: caller must be an active admin. Returns the admin's numeric id."""
    role = await repo.get_user_role(user_id)
    if role is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if role.get("disabled_at") is not None or role.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return int(role["id"])


def _ser_user(r: dict, self_id: int) -> dict:
    return {
        "id": r["id"], "name": r.get("name"), "email": r.get("email"),
        "role": r.get("role"),
        "status": "disabled" if r.get("disabled_at") is not None else "active",
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "project_count": int(r.get("project_count") or 0),
        "session_count": int(r.get("session_count") or 0),
        "storage_bytes": int(r.get("storage_bytes") or 0),
        "is_self": r["id"] == self_id,
    }


def _ser_invite(r: dict) -> dict:
    return {
        "id": r["id"], "email": r.get("email"), "role": r.get("role"),
        "status": "pending",
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.get("/overview")
async def overview(user_id: str = Depends(get_current_user_id)):
    """Everything the admin page needs in one call: stats, users, pending invites."""
    admin_id = await _require_admin(user_id)
    stats = await repo.get_overview_stats()
    users = await repo.list_users_with_stats()
    invites = await repo.list_pending_invites()
    return {
        "success": True,
        "stats": {k: int(v or 0) for k, v in stats.items()},
        "users": [_ser_user(u, admin_id) for u in users],
        "invites": [_ser_invite(i) for i in invites],
    }


@router.post("/invite")
async def invite(user_id: str = Depends(get_current_user_id),
                 email: str = Body(..., embed=True), role: str = Body("viewer", embed=True)):
    admin_id = await _require_admin(user_id)
    email = (email or "").strip()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if role not in _ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if await repo.email_taken(email):
        raise HTTPException(status_code=409, detail="Someone with that email already has an account")
    inv = await repo.create_invite(email, role, invited_by=user_id)
    logger.info("admin %s invited %s as %s", admin_id, email, role)
    return {"success": True, "invite": _ser_invite(inv)}


@router.delete("/invite/{invite_id}")
async def revoke_invite(invite_id: int, user_id: str = Depends(get_current_user_id)):
    await _require_admin(user_id)
    if not await repo.revoke_invite(invite_id):
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"success": True}


@router.post("/invite/{invite_id}/role")
async def set_invite_role(invite_id: int, user_id: str = Depends(get_current_user_id),
                          role: str = Body(..., embed=True)):
    await _require_admin(user_id)
    if role not in _ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    updated = await repo.set_invite_role(invite_id, role)
    if updated is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"success": True, "id": updated["id"], "role": updated["role"]}


@router.post("/users/{target_id}/role")
async def set_user_role(target_id: int, user_id: str = Depends(get_current_user_id),
                        role: str = Body(..., embed=True)):
    admin_id = await _require_admin(user_id)
    if role not in _ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    # No last-admin check needed: the caller is an admin and can't change their OWN role,
    # so at least one admin (the caller) always remains.
    updated = await repo.set_user_role(target_id, role)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "id": updated["id"], "role": updated["role"]}


@router.post("/users/{target_id}/disable")
async def disable_user(target_id: int, user_id: str = Depends(get_current_user_id)):
    admin_id = await _require_admin(user_id)
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    updated = await repo.set_user_disabled(target_id, True)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "id": updated["id"], "disabled": updated["disabled_at"] is not None}


@router.post("/users/{target_id}/enable")
async def enable_user(target_id: int, user_id: str = Depends(get_current_user_id)):
    await _require_admin(user_id)
    updated = await repo.set_user_disabled(target_id, False)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "id": updated["id"], "disabled": updated["disabled_at"] is not None}
