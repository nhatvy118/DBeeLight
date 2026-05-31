from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg
from fastapi import FastAPI

logger = logging.getLogger("internal")


def _get_database_url() -> str:
    return (os.getenv("DB_URL") or "").strip()


async def init_db(app: FastAPI) -> None:
    db_url = _get_database_url()
    if not db_url:
        logger.warning("DB_URL is not set. DB-backed features will be disabled.")
        app.state.db_pool = None
        return

    # Keep pool small; API server workload is light.
    app.state.db_pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=5)
    logger.info("Database pool initialized")


async def close_db(app: FastAPI) -> None:
    pool: Optional[asyncpg.Pool] = getattr(app.state, "db_pool", None)
    if pool is not None:
        await pool.close()
        logger.info("🧹 Database pool closed")

