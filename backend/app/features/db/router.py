"""Per-user DB connection (used by global sessions). Maps the FE /api/db/* contract.

The connection (DSN) is stored on the user (users.active_db_url) — never sent to the LLM.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends

from app.agent.pool import get_connection_pool, user_pool_key
from app.features.auth import repository as auth_repo
from app.features.auth.deps import get_current_user_id

logger = logging.getLogger("db")
router = APIRouter(prefix="/api/db", tags=["db"])


@router.post("/connect")
async def connect(body: dict, user_id: str = Depends(get_current_user_id)):
    logger.info("→ connect(body=*** user_id=%r)", user_id)  # autolog
    dsn = (
        f"postgresql://{quote(body.get('username') or '')}:{quote(body.get('password') or '')}"
        f"@{body.get('host')}:{int(body.get('port') or 5432)}/{body.get('database')}"
    )
    try:
        await get_connection_pool().probe(dsn)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"Could not connect: {e}"}
    await auth_repo.set_active_db_url(user_id, dsn)
    # db_url for this user's global key changed → drop the stale pooled adapter
    await get_connection_pool().invalidate(user_pool_key(user_id))
    return {"success": True, "message": "Connected"}


@router.get("/status")
async def status(user_id: str = Depends(get_current_user_id)):
    logger.info("→ status(user_id=%r)", user_id)  # autolog
    url = await auth_repo.get_active_db_url(user_id)
    return {"success": bool(url), "message": "connected" if url else "Not connected"}


@router.post("/disconnect")
async def disconnect(user_id: str = Depends(get_current_user_id)):
    logger.info("→ disconnect(user_id=%r)", user_id)  # autolog
    await auth_repo.set_active_db_url(user_id, None)
    await get_connection_pool().invalidate(user_pool_key(user_id))
    return {"success": True, "message": "Disconnected"}
