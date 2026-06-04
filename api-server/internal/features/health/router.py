from __future__ import annotations

from fastapi import APIRouter

from internal.features.health.schema import HealthOk

router = APIRouter()


@router.get("/api/health", response_model=HealthOk)
async def health() -> HealthOk:
    """Liveness probe — pure and cheap.

    If the process can serve this request, the server is up. We deliberately do
    NOT spawn or touch any agent/orchestrator here: doing so used to spawn 3 MCP
    subprocesses on a cold cache and blow past the Docker healthcheck's 5s
    timeout, flagging the container ``unhealthy`` even though nothing was wrong.
    """
    return HealthOk(status="ok", agent_initialized=True)
