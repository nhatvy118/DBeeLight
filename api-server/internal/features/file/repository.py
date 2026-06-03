"""Postgres CRUD for session-attached files and RAG chunks (pgvector)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


def _normalize_metadata(value: Any) -> dict[str, Any]:
    """Ensure metadata read from DB is always a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


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

    async def insert_chunks_batch(
        self,
        *,
        file_id: UUID,
        session_id: str,
        chunks: list[tuple[str, list[float], dict[str, Any]]],
    ) -> int:
        """chunks: list of (chunk_text, embedding, metadata dict)."""
        if not chunks:
            return 0
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                n = 0
                for text, emb, meta in chunks:
                    vec = _vector_literal(emb)
                    meta_json = json.dumps(meta, ensure_ascii=False)
                    await conn.execute(
                        """
                        INSERT INTO file_chunks (file_id, session_id, chunk_text, embedding, metadata)
                        VALUES ($1, $2, $3, $4::vector, $5::jsonb)
                        """,
                        file_id,
                        session_id,
                        text,
                        vec,
                        meta_json,
                    )
                    n += 1
                return n

    async def list_files_by_session(self, session_id: str, user_id: str) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT id, session_id, user_id, filename, local_path, mime_type, size_bytes,
                   sqlite_table_name, sqlite_db_path, summary, uploaded_at
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
                   sqlite_table_name, sqlite_db_path, summary, uploaded_at
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

    async def search_chunks(
        self,
        *,
        session_id: str,
        query_embedding: list[float],
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        vec = _vector_literal(query_embedding)
        rows = await self._pool.fetch(
            """
            SELECT fc.id, fc.file_id, fc.chunk_text, fc.metadata,
                   fc.embedding <=> $1::vector AS distance
            FROM file_chunks fc
            WHERE fc.session_id = $2
            ORDER BY fc.embedding <=> $1::vector
            LIMIT $3
            """,
            vec,
            session_id,
            top_k,
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["metadata"] = _normalize_metadata(d.get("metadata"))
            out.append(d)
        return out

