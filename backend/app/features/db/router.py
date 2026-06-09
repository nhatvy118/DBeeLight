"""Per-user DB connection (used by global sessions). Maps the FE /api/db/* contract.

The connection (DSN) is stored on the user (users.active_db_url) — never sent to the LLM.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends

from app.agent.pool import get_connection_pool
from app.features.auth import repository as auth_repo
from app.features.auth.deps import get_current_user_id

logger = logging.getLogger("db")
router = APIRouter(prefix="/api/db", tags=["db"])


@router.post("/connect")
async def connect(body: dict, user_id: str = Depends(get_current_user_id)):
    dsn = (
        f"postgresql://{quote(body.get('username') or '')}:{quote(body.get('password') or '')}"
        f"@{body.get('host')}:{int(body.get('port') or 5432)}/{body.get('database')}"
    )
    try:
        await get_connection_pool().probe(dsn)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"Could not connect: {e}"}
    await auth_repo.set_active_db_url(user_id, dsn)
    return {"success": True, "message": "Connected"}


@router.get("/status")
async def status(user_id: str = Depends(get_current_user_id)):
    url = await auth_repo.get_active_db_url(user_id)
    return {"success": bool(url), "message": "connected" if url else "Not connected"}


@router.post("/disconnect")
async def disconnect(user_id: str = Depends(get_current_user_id)):
    await auth_repo.set_active_db_url(user_id, None)
    return {"success": True, "message": "Disconnected"}
