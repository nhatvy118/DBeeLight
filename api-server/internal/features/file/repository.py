"""Postgres CRUD for session-attached files."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


class FileRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def insert_file(
        self,
        *,
        session_id: str,
        user_id: str,
        filename: str,
        local_path: str,
        mime_type: str,
        size_bytes: int,
        sqlite_table_name: str | None,
        sqlite_db_path: str | None,
        summary: str | None = None,
    ) -> UUID:
        row = await self._pool.fetchrow(
            """
            INSERT INTO files (
                session_id, user_id, filename, local_path, mime_type, size_bytes,
                sqlite_table_name, sqlite_db_path, summary
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            session_id,
            user_id,
            filename,
            local_path,
            mime_type,
            size_bytes,
            sqlite_table_name,
            sqlite_db_path,
            summary,
        )
        return row["id"]

    async def list_files_by_session(self, session_id: str, user_id: str) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT id, session_id, user_id, filename, local_path, mime_type, size_bytes,
                   sqlite_table_name, sqlite_db_path, summary, schema_snapshot, uploaded_at
            FROM files
            WHERE session_id = $1 AND user_id = $2
            ORDER BY uploaded_at ASC
            """,
            session_id,
            user_id,
        )
        return [dict(r) for r in rows]

    async def get_file(self, file_id: UUID, user_id: str) -> Optional[dict[str, Any]]:
        row = await self._pool.fetchrow(
            """
            SELECT id, session_id, user_id, filename, local_path, mime_type, size_bytes,
                   sqlite_table_name, sqlite_db_path, summary, schema_snapshot, uploaded_at
            FROM files WHERE id = $1 AND user_id = $2
            """,
            file_id,
            user_id,
        )
        return dict(row) if row else None

    async def update_file_summary(self, file_id: UUID, user_id: str, summary: str) -> None:
        await self._pool.execute(
            "UPDATE files SET summary = $1 WHERE id = $2 AND user_id = $3",
            summary,
            file_id,
            user_id,
        )

    async def update_schema_snapshot(
        self, file_id: UUID, user_id: str, snapshot: dict[str, Any]
    ) -> None:
        await self._pool.execute(
            "UPDATE files SET schema_snapshot = $1::jsonb WHERE id = $2 AND user_id = $3",
            json.dumps(snapshot, ensure_ascii=False, default=str),
            file_id,
            user_id,
        )

    async def list_files_for_user_inventory(
        self, user_id: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT id, session_id, filename, size_bytes, uploaded_at, local_path
            FROM files
            WHERE user_id = $1
            ORDER BY uploaded_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(r) for r in rows]

    async def list_file_sizes_paths_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT size_bytes, local_path FROM files WHERE user_id = $1
            """,
            user_id,
        )
        return [dict(r) for r in rows]

    async def delete_file_row(self, file_id: UUID, user_id: str) -> Optional[dict[str, Any]]:
        """Returns row before delete (for disk cleanup) or None."""
        row = await self._pool.fetchrow(
            "DELETE FROM files WHERE id = $1 AND user_id = $2 RETURNING *",
            file_id,
            user_id,
        )
        return dict(row) if row else None

