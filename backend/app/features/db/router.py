"""Per-user DB connection (used by global sessions). Maps the FE /api/db/* contract.

The connection (DSN) is stored on the user (users.active_db_url) — never sent to the LLM.
"""
from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends

from app.agent.pool import get_connection_pool, user_pool_key
from app.features.auth import repository as auth_repo
from app.features.auth.deps import get_current_user_id

logger = logging.getLogger("db")
router = APIRouter(prefix="/api/db", tags=["db"])


_GENERIC_CONNECT_ERROR = "Could not connect. Please double-check your host, port, database, username and password."


@router.post("/connect")
async def connect(body: dict, user_id: str = Depends(get_current_user_id)):
    logger.info("→ connect(body=*** user_id=%r)", user_id)  # autolog
    base_dsn = (
        f"postgresql://{quote(body.get('username') or '')}:{quote(body.get('password') or '')}"
        f"@{body.get('host')}:{int(body.get('port') or 5432)}/{body.get('database')}"
    )
    pool = get_connection_pool()
    dsn = base_dsn
    try:
        await pool.probe(dsn)
    except Exception as e1:  # noqa: BLE001
        # Managed Postgres (Neon, Supabase, RDS...) often requires SSL on the wire; the
        # plain DSN never asks for it. Retry once with SSL before giving up.
        dsn = f"{base_dsn}?ssl=require"
        try:
            await pool.probe(dsn)
        except Exception as e2:  # noqa: BLE001
            logger.warning("db/connect failed for user=%s: plain=%r ssl=%r", user_id, e1, e2)
            return {"success": False, "message": _GENERIC_CONNECT_ERROR}
    await auth_repo.set_active_db_url(user_id, dsn)
    # db_url for this user's global key changed → drop the stale pooled adapter
    await get_connection_pool().invalidate(user_pool_key(user_id))
    return {"success": True, "message": "Connected"}


@router.get("/status")
async def status(user_id: str = Depends(get_current_user_id)):
    """Connection state + redacted connection details (NEVER the password) so the UI can
    show the label and pre-fill the form without persisting secrets on the client."""
    logger.info("→ status(user_id=%r)", user_id)  # autolog
    dsn = await auth_repo.get_active_db_url(user_id)
    if not dsn:
        return {"success": False, "message": "Not connected"}
    u = urlparse(dsn)
    return {
        "success": True,
        "message": "connected",
        "host": u.hostname,
        "port": u.port,
        "database": (u.path or "").lstrip("/"),
        "username": u.username,
    }


@router.post("/disconnect")
async def disconnect(user_id: str = Depends(get_current_user_id)):
    logger.info("→ disconnect(user_id=%r)", user_id)  # autolog
    await auth_repo.set_active_db_url(user_id, None)
    await get_connection_pool().invalidate(user_pool_key(user_id))
    return {"success": True, "message": "Disconnected"}
