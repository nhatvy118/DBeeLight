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

    async def update_project_db_url(self, project_id: str, user_id: str, db_url: str) -> None:
        """
        Update the db_url for a project.
        user_id is Google sub (TEXT) for consistency with sessions.
        """
        logger.info(f"Repository: Updating db_url for project_id={project_id}, user_id={user_id}, db_url={db_url}")
        
        query = """
        UPDATE projects
        SET db_url = $1
        WHERE id = $2 AND user_id = $3
        """

        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(query, db_url.strip(), project_id, user_id)
                if result == "UPDATE 0":
                    logger.warning(f"Repository: No project found to update: project_id={project_id}, user_id={user_id}")
                else:
                    logger.info(f"Repository: Project db_url updated successfully: project_id={project_id}")
        except Exception as e:
            logger.error(f"Repository: Database error updating project db_url: {e}", exc_info=True)
            raise
