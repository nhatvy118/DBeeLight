"""asyncpg pool for the application metadata database (users/projects/sessions/...).

Unrelated to the user data database — that is managed by the agent ConnectionPool.
"""
from __future__ import annotations

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("App DB pool not initialized. Call init_pool() in lifespan.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def run_migrations(migrations_dir) -> None:
    """Run all migrations/*.sql files in order (idempotent — uses IF NOT EXISTS)."""
    from pathlib import Path

    pool = get_pool()
    files = sorted(Path(migrations_dir).glob("*.sql"))
    for f in files:
        sql = f.read_text(encoding="utf-8").strip()
        if sql:
            await pool.execute(sql)  # asyncpg can run multiple statements per file (no params)
