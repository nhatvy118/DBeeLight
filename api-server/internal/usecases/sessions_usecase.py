from __future__ import annotations

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository


class SessionsUseCase:
    def __init__(self, agent_repo: AgentRepository):
        self._agent_repo = agent_repo

    async def list_sessions(self, user_key: str, project_id: str | None = None):
        agent = await self._agent_repo.get_agent(user_key=user_key)
        return agent.session_manager.list_sessions(project_id=project_id) if agent.session_manager else []

    async def create_session(self, user_key: str, name: str | None, project_id: str | None = None):
        agent = await self._agent_repo.get_agent(user_key=user_key)
        session_id = agent.session_manager.create_session(name, project_id=project_id) if agent.session_manager else None
        session_info = agent.session_manager.get_session_info() if agent.session_manager else None
        return session_id, session_info

    async def get_session(self, user_key: str, session_id: str):
        agent = await self._agent_repo.get_agent(user_key=user_key)
        if agent.session_manager and agent.session_manager.load_session(session_id):
            session_info = agent.session_manager.get_session_info()
            messages = agent.session_manager.get_current_messages()
            return session_info, messages
        raise HTTPException(status_code=404, detail="Session not found")

