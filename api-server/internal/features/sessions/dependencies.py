from __future__ import annotations

from fastapi import Depends

from internal.features.chat.dependencies import get_agent_repository
from internal.features.chat.repository import AgentRepository
from internal.features.sessions.service import SessionsService


def get_sessions_service(
    agent_repo: AgentRepository = Depends(get_agent_repository),
) -> SessionsService:
    return SessionsService(agent_repo)
