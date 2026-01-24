from __future__ import annotations

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository


class ChatUseCase:
    def __init__(self, agent_repo: AgentRepository):
        self._agent_repo = agent_repo

    async def chat(self, user_key: str, message: str, session_id: str | None, project_id: str | None = None) -> tuple[str, str | None]:
        query = (message or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Message is required")

        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions:
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )

        if session_id and agent.session_manager:
            await agent.session_manager.load_session(session_id)

        response_text = await agent.process_query(query, verbose=False)
        session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
        current_session_id = session_info.get("session_id") if session_info else None
        return response_text, current_session_id

