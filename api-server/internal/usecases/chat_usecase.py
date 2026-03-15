from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository
from internal.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class ChatUseCase:
    def __init__(self, agent_repo: AgentRepository, project_repo: Optional[ProjectRepository] = None):
        self._agent_repo = agent_repo
        self._project_repo = project_repo

    async def chat(self, user_key: str, message: str, session_id: str | None, project_id: str | None = None) -> tuple[str, str | None]:
        logger.info(f"UseCase: Processing chat message, user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (message or "").strip()
        if not query:
            logger.error("UseCase: Message is required but was empty")
            raise HTTPException(status_code=400, detail="Message is required")

        try:
            logger.info(f"UseCase: Getting agent for user_key={user_key}")
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions:
            logger.error("UseCase: Agent initialized but no MCP servers connected")
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )

        # Đảm bảo có SessionManager
        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")

        # Validate project_id as UUID (from projects.id) if provided
        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                    logger.info(f"UseCase: Using project_id={project_id_uuid}")
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID: {project_id!r}, ignoring")

        # Auto-connect database based on context:
        # - In project: connect to project's SQLite .db file
        # - Outside project: leave as-is (user manages PostgreSQL connection manually via chat)
        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, user_key)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    # Only auto-connect if it's a SQLite path (not placeholder)
                    if db_url and not db_url.startswith("placeholder://"):
                        logger.info(f"UseCase: Auto-connecting to project database: {db_url}")
                        connect_result = await agent.connect_to_project_db(db_url)
                        logger.info(f"UseCase: Database connection result: {connect_result}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database: {e}")

        # Nếu có session_id → cố gắng load session đó
        loaded = False
        if session_id:
            logger.info(f"UseCase: Attempting to load session: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session: {session_id}")

        # Nếu không có session_id hoặc load thất bại:
        # - Nếu đang trong project (project_id_uuid) → tạo session mới gắn với project đó
        # - Nếu không có project → tạo session mới global cho user
        if not loaded:
            logger.info(f"UseCase: Creating new session, project_id={project_id_uuid}")
            await agent.session_manager.create_session(session_name=None, project_id=project_id_uuid)

        logger.info(f"UseCase: Processing query: {query[:100]}...")
        try:
            response_text, agent_id = await agent.process_query(query, verbose=False)
            session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
            current_session_id = session_info.get("session_id") if session_info else None
            logger.info(f"UseCase: Query processed successfully, session_id={current_session_id}, agent={agent_id}")
            return response_text, current_session_id
        except Exception as e:
            logger.error(f"UseCase: Error processing query: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}") from e

    async def execute_sql(self, user_key: str, sql: str, session_id: str | None, project_id: str | None = None, lang: str = "en") -> tuple[str, str | None]:
        """
        Execute a raw SQL statement that was previously previewed to the user.
        This reuses the same agent + project DB auto-connect + session logic as chat().
        """
        logger.info(f"UseCase: Executing SQL for user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (sql or "").strip()
        if not query:
            logger.error("UseCase: SQL is required but was empty")
            raise HTTPException(status_code=400, detail="SQL is required")

        try:
            logger.info(f"UseCase: Getting agent for user_key={user_key} (execute_sql)")
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent (execute_sql): {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions:
            logger.error("UseCase: Agent initialized but no MCP servers connected (execute_sql)")
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )

        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent (execute_sql)")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")

        # Validate project_id as UUID (from projects.id) if provided
        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                    logger.info(f"UseCase: Using project_id={project_id_uuid} (execute_sql)")
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID in execute_sql: {project_id!r}, ignoring")

        # Auto-connect database based on context (same as chat)
        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, user_key)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    if db_url and not db_url.startswith("placeholder://"):
                        logger.info(f"UseCase: Auto-connecting to project database (execute_sql): {db_url}")
                        connect_result = await agent.connect_to_project_db(db_url)
                        logger.info(f"UseCase: Database connection result (execute_sql): {connect_result}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database in execute_sql: {e}")

        # Load or create session (so history / project context is consistent)
        loaded = False
        if session_id:
            logger.info(f"UseCase: Attempting to load session in execute_sql: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session in execute_sql: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session in execute_sql: {session_id}")

        if not loaded:
            logger.info(f"UseCase: Creating new session for execute_sql, project_id={project_id_uuid}")
            await agent.session_manager.create_session(session_name=None, project_id=project_id_uuid)

        logger.info(f"UseCase: Executing SQL (first 200 chars): {query[:200]}...")
        try:
            # Bypass LLM routing: call orchestrator helper to run SQL directly on DB MCP server
            result_text = await agent.execute_sql(query, lang=lang)
            session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
            current_session_id = session_info.get("session_id") if session_info else None
            logger.info(f"UseCase: SQL executed successfully, session_id={current_session_id}")
            return result_text, current_session_id
        except Exception as e:
            logger.error(f"UseCase: Error executing SQL: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to execute SQL: {str(e)}") from e

