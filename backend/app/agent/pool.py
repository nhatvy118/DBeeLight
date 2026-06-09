"""ConnectionPool — holds adapters per project_id, lives in the api-server process.

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
        # project_id -> (db_url, adapter)
        self._projects: dict[str, tuple[str, DatabaseAdapter]] = {}
        # session-file path -> adapter
        self._sessions: dict[str, DatabaseAdapter] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def adapter_for(self, project_id: str, db_url: str) -> DatabaseAdapter:
        """Adapter for the project main DB. Created if missing / db_url changed."""
        async with self._lock(f"p:{project_id}"):
            cached = self._projects.get(project_id)
            if cached is not None and cached[0] == db_url:
                return cached[1]
            if cached is not None:
                await cached[1].dispose()  # db_url changed → drop the old adapter
            adapter = make_adapter(db_url)
            self._projects[project_id] = (db_url, adapter)
            logger.info("Pool: created adapter for project=%s (%s)", project_id, adapter.engine_name)
            return adapter

    async def session_adapter_for(
        self, path: str, allowed_tables: frozenset[str] | None = None
    ) -> DatabaseAdapter:
        """Adapter for the session SQLite file (upload). Cached by path."""
        async with self._lock(f"s:{path}"):
            cached = self._sessions.get(path)
            if cached is not None:
                cached.allowed_tables = allowed_tables
                return cached
            adapter = make_adapter(path, allowed_tables=allowed_tables)
            self._sessions[path] = adapter
            return adapter

    async def probe(self, db_url: str) -> None:
        """Open + SELECT 1 to validate the connection (used by Connect DB). Not cached."""
        adapter = make_adapter(db_url)
        try:
            await adapter.ping()
        finally:
            await adapter.dispose()

    async def invalidate_project(self, project_id: str) -> None:
        cached = self._projects.pop(project_id, None)
        if cached is not None:
            await cached[1].dispose()

    async def close_all(self) -> None:
        for _url, adapter in self._projects.values():
            await adapter.dispose()
        for adapter in self._sessions.values():
            await adapter.dispose()
        self._projects.clear()
        self._sessions.clear()


_singleton: ConnectionPool | None = None


def get_connection_pool() -> ConnectionPool:
    global _singleton
    if _singleton is None:
        _singleton = ConnectionPool()
    return _singleton
