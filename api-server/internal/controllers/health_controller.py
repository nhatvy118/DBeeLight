from __future__ import annotations

from fastapi import APIRouter, Depends

from internal.controllers.schemas import HealthOk
from internal.dependencies import get_agent_repository
from internal.repositories.agent_repository import AgentRepository


router = APIRouter()

@router.get("/api/health", response_model=HealthOk)
async def health(agent_repo: AgentRepository = Depends(get_agent_repository)) -> HealthOk:
    # "agent_initialized" means we can successfully init and have sessions/tools
    try:
        agent = await agent_repo.get_agent(user_key="anonymous")
        initialized = bool(agent.sessions)
    except Exception:
        initialized = False
    return HealthOk(status="ok", agent_initialized=initialized)

