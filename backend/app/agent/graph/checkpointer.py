"""Shared LangGraph checkpointer: Postgres (durable) or MemorySaver (dev).

Workflow state (interrupt/resume) lives in Postgres, keyed by thread_id + checkpoint_ns,
so any replica can resume ⇒ still stateless at the process level.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger("agent.graph.checkpointer")

_cp: Any = None
_cp_cm: Any = None
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _pg_uri() -> str | None:
    uri = (get_settings().database_url or "").strip()
    return uri or None


async def get_async_checkpointer() -> Any:
    """Return a process-wide async checkpointer."""
    global _cp, _cp_cm
    async with _get_lock():
        if _cp is not None:
            return _cp

        uri = _pg_uri()
        if uri:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                # psycopg uses the postgresql:// scheme (not asyncpg)
                pg_uri = uri.replace("postgresql+asyncpg://", "postgresql://")
                _cp_cm = AsyncPostgresSaver.from_conn_string(pg_uri)
                _cp = await _cp_cm.__aenter__()
                await _cp.setup()
                logger.info("LangGraph checkpointer: AsyncPostgresSaver")
                return _cp
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to init Postgres checkpointer (%s) → MemorySaver", e)

        from langgraph.checkpoint.memory import MemorySaver

        _cp = MemorySaver()
        logger.info("LangGraph checkpointer: MemorySaver (dev/fallback)")
        return _cp
