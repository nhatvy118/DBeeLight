from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


class ProjectRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create_project(self, *, user_id: str, name: str, description: Optional[str], db_url: str) -> dict[str, Any]:
        """
        Create a new project. Returns the created project.
        user_id is Google sub (TEXT) for consistency with sessions.
        Database will automatically generate the project_id (UUID).
        """
        logger.info(f"Repository: Creating project with user_id={user_id}, name={name}, description={description}, db_url={db_url}")

        name = (name or "").strip()
        if not name:
            logger.error("Repository: name is required but was empty")
            raise ValueError("name is required")

        # Use default placeholder if db_url is not provided (database requires NOT NULL)
        db_url = (db_url or "").strip()
        if not db_url:
            db_url = "placeholder://not-configured"
            logger.info(f"Repository: Using placeholder db_url: {db_url}")

        query = """
        INSERT INTO projects (name, description, user_id, db_url)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, description, user_id, db_url, created_at
        """

        try:
            logger.info(f"Repository: Executing query with params: name={name}, description={description}, user_id={user_id}, db_url={db_url}")
            async with self._pool.acquire() as conn:
                row: Optional[asyncpg.Record] = await conn.fetchrow(
                    query, name, description, user_id, db_url.strip()
                )
                if row is None:
                    logger.error("Repository: INSERT query returned no row")
                    raise RuntimeError("Failed to create project")
                logger.info(f"Repository: Project created successfully, id={row.get('id')}")
                return dict(row)
        except Exception as e:
            logger.error(f"Repository: Database error creating project: {e}", exc_info=True)
            raise

    async def get_projects_by_user(self, user_id: str) -> list[dict[str, Any]]:
        """
        Get all projects for a user.
        user_id is Google sub (TEXT) for consistency with sessions.
        """
        query = """
        SELECT id, name, description, user_id, db_url, created_at
        FROM projects
        WHERE user_id = $1
        ORDER BY created_at DESC
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, user_id)
            return [dict(row) for row in rows]

    async def get_project_by_id(self, project_id: str, user_id: str) -> Optional[dict[str, Any]]:
        """
        Get a project by ID, ensuring it belongs to the user.
        user_id is Google sub (TEXT) for consistency with sessions.
        """
        query = """
        SELECT id, name, description, user_id, db_url, created_at
        FROM projects
        WHERE id = $1 AND user_id = $2
        """

        async with self._pool.acquire() as conn:
            row: Optional[asyncpg.Record] = await conn.fetchrow(query, project_id, user_id)
            return dict(row) if row else None

    async def get_session_ids_for_project(self, project_id: str, user_id: str) -> list[str]:
        """All session ids belonging to a project (for file/temp-db cleanup before delete)."""
        query = "SELECT id FROM session WHERE user_id = $1 AND project_id = $2"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, user_id, project_id)
            return [str(row["id"]) for row in rows]

    async def delete_project(self, project_id: str, user_id: str) -> Optional[dict[str, Any]]:
        """
        Delete a project and all its chat sessions, ensuring it belongs to the user.

        Sessions are deleted first because ``session.project_id`` has no
        ON DELETE CASCADE; deleting them also cascades chat_shares and file rows.
        Runs in a transaction. Returns the deleted project row (incl ``db_url``
        so the caller can remove the SQLite file), or None if not found/owned.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM session WHERE user_id = $1 AND project_id = $2",
                    user_id,
                    project_id,
                )
                row: Optional[asyncpg.Record] = await conn.fetchrow(
                    "DELETE FROM projects WHERE id = $1 AND user_id = $2 RETURNING id, db_url",
                    project_id,
                    user_id,
                )
                if row is None:
                    logger.warning(f"Repository: No project found to delete: project_id={project_id}, user_id={user_id}")
                    return None
                logger.info(f"Repository: Deleted project {project_id} and its sessions for user_id={user_id}")
                return dict(row)
