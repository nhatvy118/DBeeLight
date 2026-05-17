from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Request

from internal.features.chat.repository import AgentRepository
from internal.features.chat.service import ChatService
from internal.features.file.service import FileService
from internal.features.project.repository import ProjectRepository
from internal.features.share.repository import ChatShareRepository


@lru_cache
def _agent_repository_singleton() -> AgentRepository:
    # Singleton-ish: AgentRepository keeps the initialized agent + async lock.
    return AgentRepository()


def get_agent_repository(request: Request) -> AgentRepository:
    repo = _agent_repository_singleton()
    repo.set_db_pool(getattr(request.app.state, "db_pool", None))
    return repo


def get_chat_service(
    request: Request,
    agent_repo: AgentRepository = Depends(get_agent_repository),
) -> ChatService:
    pool = getattr(request.app.state, "db_pool", None)
    project_repo = ProjectRepository(pool) if pool else None
    share_repo = ChatShareRepository(pool) if pool else None
    file_service = FileService(pool, project_repo) if pool else None
    return ChatService(agent_repo, project_repo, share_repo, file_service)
