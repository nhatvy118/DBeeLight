"""Shared LangGraph checkpointer: Postgres (durable) or in-memory fallback.

Set one of:
  - LANGGRAPH_CHECKPOINT_DB_URL — dedicated DB for graph checkpoints (optional)
  - DATABASE_URL or DB_URL — same as api-server (`internal/db.py`)

Example:
  postgresql://postgres:postgres@localhost:5442/postgres?sslmode=disable

First successful Postgres init runs AsyncPostgresSaver.setup() (checkpoint tables).
If no URI is set, MemorySaver is used (dev / tests).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_cp: Any = None
_cp_lock: Optional[asyncio.Lock] = None
_pool: Any = None


def _resolve_postgres_uri() -> str | None:
    for key in (
        "LANGGRAPH_CHECKPOINT_DB_URL",
        "DATABASE_URL",
        "DB_URL",
    ):
        v = (os.getenv(key) or "").strip()
        if v:
            return v
    return None


def _get_lock() -> asyncio.Lock:
    global _cp_lock
    if _cp_lock is None:
        _cp_lock = asyncio.Lock()
    return _cp_lock


async def get_async_checkpointer() -> Any:
    """Return a process-wide async-compatible checkpointer (Postgres or MemorySaver)."""
    global _cp, _pool

    async with _get_lock():
        if _cp is not None:
            return _cp

        uri = _resolve_postgres_uri()
        if not uri:
            logger.debug(
                "No LANGGRAPH_CHECKPOINT_DB_URL / DATABASE_URL / DB_URL; "
                "using MemorySaver for LangGraph checkpoints"
            )
            _cp = MemorySaver()
            return _cp

        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _pool = AsyncConnectionPool(
            conninfo=uri,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,
            min_size=1,
            max_size=10,
        )
        await _pool.open()
        _cp = AsyncPostgresSaver(_pool)
        await _cp.setup()
        logger.info("LangGraph AsyncPostgresSaver initialized and setup() completed")
        return _cp
