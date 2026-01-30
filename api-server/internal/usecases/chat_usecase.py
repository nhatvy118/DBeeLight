from __future__ import annotations

import logging

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository

logger = logging.getLogger(__name__)


class ChatUseCase:
    def __init__(self, agent_repo: AgentRepository):
        self._agent_repo = agent_repo

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

        # Parse project_id (nếu có) thành số; nếu không hợp lệ thì bỏ qua
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
        # - Nếu đang trong project (numeric_project_id != None) → tạo session mới gắn với project đó
        # - Nếu không có project → tạo session mới global cho user
        if not loaded:
            logger.info(f"UseCase: Creating new session, project_id={numeric_project_id}")
            await agent.session_manager.create_session(session_name=None, project_id=numeric_project_id)

        logger.info(f"UseCase: Processing query: {query[:100]}...")
        try:
            response_text = await agent.process_query(query, verbose=False)
            session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
            current_session_id = session_info.get("session_id") if session_info else None
            logger.info(f"UseCase: Query processed successfully, session_id={current_session_id}")
            return response_text, current_session_id
        except Exception as e:
            logger.error(f"UseCase: Error processing query: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}") from e

