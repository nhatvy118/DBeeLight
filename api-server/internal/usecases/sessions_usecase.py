from __future__ import annotations

import logging

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository

logger = logging.getLogger(__name__)


class SessionsUseCase:
    def __init__(self, agent_repo: AgentRepository):
        self._agent_repo = agent_repo

    async def list_sessions(self, user_key: str, project_id: str | None = None, unassigned_only: bool = False):
        logger.info(f"UseCase: Listing sessions, user_key={user_key}, project_id={project_id}, unassigned_only={unassigned_only}")
        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
            if not agent.session_manager:
                logger.warning(f"UseCase: Session manager not available for user_key={user_key}")
                return []

            numeric_project_id: int | None = None
            if project_id is not None:
                project_id_str = str(project_id).strip()
                if project_id_str:
                    try:
                        numeric_project_id = int(project_id_str)
                        logger.info(f"UseCase: Parsed project_id={numeric_project_id}")
                    except ValueError:
                        logger.warning(f"UseCase: Invalid project_id format: {project_id_str}, ignoring")
                        numeric_project_id = None

            sessions = await agent.session_manager.list_sessions(project_id=numeric_project_id, unassigned_only=unassigned_only)
            logger.info(f"UseCase: Found {len(sessions)} sessions")
            return sessions
        except Exception as e:
            logger.error(f"UseCase: Error listing sessions: {e}", exc_info=True)
            raise

    async def create_session(self, user_key: str, name: str | None, project_id: str | None = None):
        logger.info(f"UseCase: Creating session, user_key={user_key}, name={name}, project_id={project_id}")
        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
            if not agent.session_manager:
                logger.warning(f"UseCase: Session manager not available for user_key={user_key}")
                return None, None

            numeric_project_id: int | None = None
            if project_id is not None:
                project_id_str = str(project_id).strip()
                if project_id_str:
                    try:
                        numeric_project_id = int(project_id_str)
                        logger.info(f"UseCase: Parsed project_id={numeric_project_id}")
                    except ValueError:
                        logger.warning(f"UseCase: Invalid project_id format: {project_id_str}, ignoring")
                        numeric_project_id = None

            session_id = await agent.session_manager.create_session(name, project_id=numeric_project_id)
            session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
            logger.info(f"UseCase: Session created successfully, session_id={session_id}")
            return session_id, session_info
        except Exception as e:
            logger.error(f"UseCase: Error creating session: {e}", exc_info=True)
            raise

    async def get_session(self, user_key: str, session_id: str):
        logger.info(f"UseCase: Getting session, user_key={user_key}, session_id={session_id}")
        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
            if agent.session_manager and await agent.session_manager.load_session(session_id):
                logger.info(f"UseCase: Session loaded successfully: {session_id}")
                session_info = await agent.session_manager.get_session_info()
                messages = await agent.session_manager.get_current_messages()
                logger.info(f"UseCase: Found {len(messages)} messages in session")
                return session_info, messages
            logger.warning(f"UseCase: Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"UseCase: Error getting session: {e}", exc_info=True)
            raise

