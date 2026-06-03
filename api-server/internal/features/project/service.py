from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from internal.features.project.repository import ProjectRepository
from internal.features.project.sqlite_helper import (
    delete_sqlite_database,
    generate_sqlite_db_path,
    get_sqlite_db_url_from_path,
    init_sqlite_database,
)

if TYPE_CHECKING:
    from internal.features.file.service import FileService

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, project_repo: ProjectRepository):
        self._project_repo = project_repo

    def _get_user_key(self, request: Request) -> str:
        """
        Get user_key (Google sub) from session. Raises HTTPException if not authenticated.
        """
        user = request.session.get("user")
        if not isinstance(user, dict):
            logger.warning("User not authenticated. No user in session")
            raise HTTPException(status_code=401, detail="User not authenticated")

        google_sub = user.get("sub")
        if not isinstance(google_sub, str) or not google_sub.strip():
            logger.warning(f"User not authenticated. Missing Google sub: {google_sub}")
            raise HTTPException(status_code=401, detail="User not authenticated")

        logger.info(f"Getting user_key (Google sub) from session: {google_sub}")
        return google_sub.strip()

    async def create_project(self, request: Request, name: str, description: str | None, db_url: str) -> dict:
        """
        Create a new project for the authenticated user.
        If db_url is not provided, automatically creates a SQLite database file for the project.
        """
        user_key = self._get_user_key(request)
        logger.info(f"Creating project: name={name}, description={description}, db_url={db_url}, user_key={user_key}")

        try:
            final_db_url = db_url

            if not db_url or db_url.strip() == "" or db_url == "placeholder://not-configured":
                sqlite_path = generate_sqlite_db_path()
                if init_sqlite_database(sqlite_path):
                    final_db_url = get_sqlite_db_url_from_path(sqlite_path)
                    logger.info(f"SQLite database file created: {sqlite_path}, URL: {final_db_url}")
                else:
                    logger.warning(f"Failed to create SQLite database file, using placeholder")
                    final_db_url = "placeholder://not-configured"

            project = await self._project_repo.create_project(
                user_id=user_key,
                name=name,
                description=description,
                db_url=final_db_url,
            )

            project_id = str(project["id"])
            logger.info(f"Project created successfully: id={project_id}, db_url={final_db_url}")

            return {
                "success": True,
                "project": {
                    "id": project_id,
                    "name": project["name"],
                    "description": project.get("description"),
                    "created_at": project["created_at"].isoformat() if project.get("created_at") else None,
                },
            }
        except ValueError as e:
            logger.error(f"Validation error creating project: {e}")
            raise HTTPException(status_code=400, detail=str(e)) from e
        except HTTPException:
            raise
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Error creating project: {e}\n{error_trace}")
            error_detail = f"Failed to create project: {str(e)}"
            raise HTTPException(status_code=500, detail=error_detail) from e

    async def delete_project(self, request: Request, project_id: str, file_service: "FileService") -> dict:
        """
        Delete a project and everything attached to it:
          - all chat sessions of the project (rows) + their uploaded files / temp DBs
          - chat_shares (cascaded by the row deletes)
          - the project's SQLite database file on disk
        """
        user_key = self._get_user_key(request)

        project = await self._project_repo.get_project_by_id(project_id, user_key)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        try:
            # 1. Remove on-disk files/temp DBs per session. Lean purge: just rmtree
            #    the file_handle session tree + unlink the temp DB. No per-file row
            #    or chat-message work — the session rows (and cascaded file rows)
            #    are deleted in step 2, and the project SQLite file in step 3.
            session_ids = await self._project_repo.get_session_ids_for_project(project_id, user_key)
            for sid in session_ids:
                try:
                    file_service.purge_session_disk(sid, user_key)
                except Exception as e:
                    logger.warning(f"Session disk purge failed for {sid} (project {project_id}): {e}")

            # 2. Delete session rows + project row in one transaction.
            deleted = await self._project_repo.delete_project(project_id, user_key)
            if deleted is None:
                # Lost a race (already deleted) — treat as not found.
                raise HTTPException(status_code=404, detail="Project not found")

            # 3. Delete the project's SQLite file (safe: confined to managed dir).
            delete_sqlite_database(deleted.get("db_url"))

            logger.info(f"Project deleted: id={project_id}, sessions_removed={len(session_ids)}")
            return {"success": True, "deleted_sessions": len(session_ids)}
        except HTTPException:
            raise
        except Exception as e:
            import traceback
            logger.error(f"Error deleting project {project_id}: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}") from e

    async def list_projects(self, request: Request) -> dict:
        """
        List all projects for the authenticated user.
        """
        user_key = self._get_user_key(request)

        try:
            projects = await self._project_repo.get_projects_by_user(user_key)
            return {
                "success": True,
                "projects": [
                    {
                        "id": str(project["id"]),
                        "name": project["name"],
                        "description": project.get("description"),
                        "created_at": project["created_at"].isoformat() if project.get("created_at") else None,
                    }
                    for project in projects
                ],
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list projects: {str(e)}") from e
