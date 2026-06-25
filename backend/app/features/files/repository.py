from __future__ import annotations
import logging

import uuid

from app.db import get_pool

logger = logging.getLogger("features.files.repository")


async def insert_file(
    user_id: str, session_id: str, filename: str, disk_path: str | None,
    size_bytes: int = 0, file_id: str | None = None,
) -> dict:
    logger.info("→ insert_file(user_id=%r session_id=%r filename=%r disk_path=%r size_bytes=%r file_id=%r)", user_id, session_id, filename, disk_path, size_bytes, file_id)  # autolog
    pool = get_pool()
    fid = file_id or str(uuid.uuid4())
    row = await pool.fetchrow(
        """
        INSERT INTO files (id, user_id, session_id, filename, disk_path, size_bytes)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, filename, size_bytes, created_at
        """,
        fid, user_id, session_id, filename, disk_path, size_bytes,
    )
    return dict(row)


async def list_for_session(session_id: str) -> list[dict]:
    logger.info("→ list_for_session(session_id=%r)", session_id)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, filename, disk_path, size_bytes, created_at "
        "FROM files WHERE session_id = $1 ORDER BY created_at ASC",
        session_id,
    )
    return [dict(r) for r in rows]


async def list_for_user(user_id: str) -> list[dict]:
    logger.info("→ list_for_user(user_id=%r)", user_id)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, filename, size_bytes, created_at FROM files "
        "WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_file_full(file_id: str, user_id: str) -> dict | None:
    """Row needed to clean up a file's backing storage on delete (the disk workbook)."""
    logger.info("→ get_file_full(file_id=%r user_id=%r)", file_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, session_id, filename, disk_path FROM files WHERE id=$1 AND user_id=$2",
        file_id, user_id,
    )
    return dict(row) if row else None


async def get_file(file_id: str, user_id: str) -> dict | None:
    logger.info("→ get_file(file_id=%r user_id=%r)", file_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, filename, disk_path, size_bytes FROM files WHERE id=$1 AND user_id=$2",
        file_id, user_id,
    )
    return dict(row) if row else None


async def delete_file(file_id: str, user_id: str) -> bool:
    logger.info("→ delete_file(file_id=%r user_id=%r)", file_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM files WHERE id=$1 AND user_id=$2 RETURNING id", file_id, user_id
    )
    return row is not None


async def user_storage(user_id: str) -> tuple[int, int]:
    """(total size_bytes, file_count) for the user."""
    logger.info("→ user_storage(user_id=%r)", user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT COALESCE(SUM(size_bytes),0) AS b, COUNT(*) AS c FROM files WHERE user_id=$1",
        user_id,
    )
    return int(row["b"] or 0), int(row["c"] or 0)
