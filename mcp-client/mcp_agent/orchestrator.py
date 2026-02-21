"""Multi-agent orchestrator: routes queries to the appropriate agent(s)."""

import logging
from typing import Any, Dict, List

from openai import OpenAI

logger = logging.getLogger(__name__)

from mcp_agent.base_agent import BaseAgent
from mcp_agent.session import SessionManager


class MultiAgentOrchestrator:
    """
    Holds multiple agents and routes each user query to the best agent.
    Uses a single shared SessionManager so conversation history is unified.
    """

    def __init__(
        self,
        agents: List[BaseAgent],
        session_manager: SessionManager,
        router_model: str = "gpt-4o-mini",
    ):
        if not agents:
            raise ValueError("At least one agent is required")
        self._agents: Dict[str, BaseAgent] = {a.agent_id: a for a in agents}
        self.session_manager = session_manager
        self._openai = OpenAI()
        self._router_model = router_model
        self._router_prompt = self._build_router_prompt()

    def _build_router_prompt(self) -> str:
        agent_list = ", ".join(self._agents.keys())
        return f"""You are a router. Given the user message, choose exactly one agent to handle it.
Available agents: {agent_list}.

Reply with ONLY the agent id (one word), nothing else. No explanation."""

    async def _route(self, query: str) -> str:
        """Decide which agent should handle this query. Returns agent_id."""
        if len(self._agents) == 1:
            return next(iter(self._agents.keys()))
        response = self._openai.chat.completions.create(
            model=self._router_model,
            messages=[
                {"role": "system", "content": self._router_prompt},
                {"role": "user", "content": query},
            ],
            temperature=0,
        )
        choice = response.choices[0]
        if not choice.message or not choice.message.content:
            return next(iter(self._agents.keys()))
        agent_id = choice.message.content.strip().lower().split()[0] if choice.message.content else ""
        return agent_id if agent_id in self._agents else next(iter(self._agents.keys()))

    @property
    def sessions(self) -> Dict[str, Any]:
        """Expose sessions from the first agent for API compatibility (e.g. health check)."""
        first = next(iter(self._agents.values()))
        return first.sessions

    async def process_query(self, query: str, verbose: bool = False) -> tuple[str, str]:
        """Route the query to the appropriate agent and return (response_text, agent_id)."""
        agent_id = await self._route(query)
        agent = self._agents[agent_id]
        if verbose:
            print(f"[Orchestrator] Routing to agent: {agent_id}")
        response_text = await agent.process_query(query, verbose=verbose)
        return response_text, agent_id

    async def connect_to_project_db(self, db_url: str) -> str:
        """
        Connect the database agent to a project's SQLite database.
        
        Args:
            db_url: Path to the SQLite database file (e.g., "sqlite:///path/to/project.db")
        
        Returns:
            Result message from the connection attempt.
        """
        # Find database agent
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"
        
        # Find connect_sqlite tool in agent's sessions
        for server_name, session in db_agent.sessions.items():
            try:
                # Call connect_sqlite tool
                result = await session.call_tool("connect_sqlite", {"file_path": db_url})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                return result_content
            except Exception as e:
                # Tool not found in this server, continue
                continue
        
        return "connect_sqlite tool not found in any connected server"

    async def disconnect_database(self) -> str:
        """
        Disconnect the database agent from any connected database.
        
        Returns:
            Result message from the disconnection attempt.
        """
        # Find database agent
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"
        
        # Find disconnect_database tool in agent's sessions
        for server_name, session in db_agent.sessions.items():
            try:
                # Call disconnect_database tool
                result = await session.call_tool("disconnect_database", {})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                return result_content
            except Exception as e:
                # Tool not found in this server, continue
                continue
        
        return "disconnect_database tool not found in any connected server"

    async def cleanup(self) -> None:
        """Clean up all agents."""
        for agent in self._agents.values():
            await agent.cleanup()
