"""ConnectionPool — holds adapters per project_id, lives in the backend process.

This is a "resource cache" (not identity state): any replica can rebuild it
from db_url. Many requests on the same project share one adapter; the AsyncEngine inside
the adapter already has a connection pool safe for concurrent access.
"""
from __future__ import annotations

import asyncio
import logging

from app.agent.adapters import DatabaseAdapter, make_adapter

logger = logging.getLogger("agent.pool")


class ConnectionPool:
    def __init__(self) -> None:
        # pool key (project_id) -> adapter
        self._projects: dict[str, DatabaseAdapter] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def adapter_for(self, key: str, db_url: str) -> DatabaseAdapter:
        """Adapter for a pooled DB, keyed by project_id.

        Created on miss, reused on hit. The cache is keyed purely by `key`; it does
        NOT track db_url. Callers MUST invalidate(key) whenever that key's db_url
        changes (project re-provision, DB connect/disconnect) — otherwise this
        keeps serving the old adapter.
        """
        async with self._lock(key):
            cached = self._projects.get(key)
            if cached is not None:
                return cached
            adapter = make_adapter(db_url)
            self._projects[key] = adapter
            logger.info("Pool: created adapter for key=%s (%s)", key, adapter.engine_name)
            return adapter

    async def probe(self, db_url: str) -> None:
        """Open + SELECT 1 to validate the connection (used by Connect DB). Not cached."""
        adapter = make_adapter(db_url)
        try:
            await adapter.ping()
        finally:
            await adapter.dispose()

    async def invalidate(self, key: str) -> None:
        """Drop + dispose the adapter for a pool key (project_id)."""
        adapter = self._projects.pop(key, None)
        if adapter is not None:
            await adapter.dispose()

    async def close_all(self) -> None:
        for adapter in self._projects.values():
            await adapter.dispose()
        self._projects.clear()


_singleton: ConnectionPool | None = None


def get_connection_pool() -> ConnectionPool:
    global _singleton
    if _singleton is None:
        _singleton = ConnectionPool()
    return _singleton
