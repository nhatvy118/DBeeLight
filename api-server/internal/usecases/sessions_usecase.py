from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository

logger = logging.getLogger(__name__)


def _parse_project_id_uuid(project_id: str | None) -> str | None:
    """Validate and return project_id as UUID string, or None if invalid/empty."""
    if project_id is None:
        return None
    s = str(project_id).strip()
    if not s:
        return None
    try:
        uuid.UUID(s)
        return s
    except (ValueError, TypeError):
        logger.warning(f"UseCase: Invalid project_id UUID format: {project_id!r}, ignoring")
        return None


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

            project_id_uuid = _parse_project_id_uuid(project_id)
            if project_id_uuid:
                logger.info(f"UseCase: Filtering by project_id={project_id_uuid}")

            sessions = await agent.session_manager.list_sessions(project_id=project_id_uuid, unassigned_only=unassigned_only)
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

            project_id_uuid = _parse_project_id_uuid(project_id)
            if project_id_uuid:
                logger.info(f"UseCase: Creating session with project_id={project_id_uuid}")

            session_id = await agent.session_manager.create_session(name, project_id=project_id_uuid)
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
                # Ensure latest in-memory/Redis messages are persisted before returning history.
                await agent.session_manager.flush_current_session()
                session_info = await agent.session_manager.get_session_info()
                messages = await agent.session_manager.get_current_messages()
                sql_action_states = await agent.session_manager.get_sql_action_states(session_id)
                if isinstance(session_info, dict):
                    session_info["sql_action_states"] = sql_action_states
                logger.info(f"UseCase: Found {len(messages)} messages in session")
                return session_info, messages
            logger.warning(f"UseCase: Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"UseCase: Error getting session: {e}", exc_info=True)
            raise

