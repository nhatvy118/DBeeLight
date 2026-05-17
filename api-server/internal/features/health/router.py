from __future__ import annotations

from fastapi import APIRouter, Depends

from internal.features.chat.dependencies import get_agent_repository
from internal.features.chat.repository import AgentRepository
from internal.features.health.schema import HealthOk

router = APIRouter()


@router.get("/api/health", response_model=HealthOk)
async def health(agent_repo: AgentRepository = Depends(get_agent_repository)) -> HealthOk:
    try:
        agent = await agent_repo.get_agent(user_key="anonymous")
        initialized = bool(agent.sessions)
    except Exception:
        initialized = False
    return HealthOk(status="ok", agent_initialized=initialized)
