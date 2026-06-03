from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from internal.features.admin.repository import AdminRepository

logger = logging.getLogger(__name__)


class AdminService:
    def __init__(self, admin_repo: AdminRepository):
        self._repo = admin_repo

    async def require_admin(self, request: Request) -> int:
        """Authorize the current session as an active admin. Returns the user id.

        Raises 401 if not logged in, 403 if not an admin or the account is disabled.
        """
        user_id = request.session.get("user_id")
        if not isinstance(user_id, int):
            raise HTTPException(status_code=401, detail="Not authenticated")
        role = await self._repo.get_user_role(user_id)
        if role is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if role.get("disabled_at") is not None or not role.get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin access required")
        return user_id

    @staticmethod
    def _serialize_user(row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row.get("name"),
            "email": row.get("email"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "is_admin": bool(row.get("is_admin")),
            "disabled": row.get("disabled_at") is not None,
            "disabled_at": row["disabled_at"].isoformat() if row.get("disabled_at") else None,
            "project_count": int(row.get("project_count") or 0),
            "session_count": int(row.get("session_count") or 0),
            "storage_bytes": int(row.get("storage_bytes") or 0),
        }

    async def list_users(self, request: Request) -> dict:
        await self.require_admin(request)
        rows = await self._repo.list_users_with_stats()
        return {"success": True, "users": [self._serialize_user(r) for r in rows]}

    async def get_stats(self, request: Request) -> dict:
        await self.require_admin(request)
        s = await self._repo.get_overview_stats()
        return {
            "success": True,
            "stats": {
                "total_users": int(s.get("total_users") or 0),
                "disabled_users": int(s.get("disabled_users") or 0),
                "admin_users": int(s.get("admin_users") or 0),
                "total_projects": int(s.get("total_projects") or 0),
                "total_sessions": int(s.get("total_sessions") or 0),
                "total_storage_bytes": int(s.get("total_storage_bytes") or 0),
            },
        }

    async def set_disabled(self, request: Request, target_user_id: int, disabled: bool) -> dict:
        admin_id = await self.require_admin(request)
        if disabled and target_user_id == admin_id:
            raise HTTPException(status_code=400, detail="You cannot disable your own account")
        updated = await self._repo.set_user_disabled(target_user_id, disabled)
        if updated is None:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "id": updated["id"], "disabled": updated["disabled_at"] is not None}
