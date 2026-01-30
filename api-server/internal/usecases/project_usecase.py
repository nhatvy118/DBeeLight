from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from internal.repositories.project_repository import ProjectRepository
from internal.utils.sqlite_helper import generate_sqlite_db_path, get_sqlite_db_url_from_path, init_sqlite_database

logger = logging.getLogger(__name__)


class ProjectUseCase:
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
            # If db_url is not provided, generate SQLite file with random name and get SQLite URL
            final_db_url = db_url
            
            if not db_url or db_url.strip() == "" or db_url == "placeholder://not-configured":                
                # Generate SQLite database file with random name
                sqlite_path = generate_sqlite_db_path()
                if init_sqlite_database(sqlite_path):
                    final_db_url = get_sqlite_db_url_from_path(sqlite_path)
                    logger.info(f"SQLite database file created: {sqlite_path}, URL: {final_db_url}")
                else:
                    logger.warning(f"Failed to create SQLite database file, using placeholder")
                    final_db_url = "placeholder://not-configured"
            
            # Create project in database with SQLite URL (database will generate project_id)
            project = await self._project_repo.create_project(
                user_id=user_key,
                name=name,
                description=description,
                db_url=final_db_url
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
                }
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
                ]
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list projects: {str(e)}") from e
