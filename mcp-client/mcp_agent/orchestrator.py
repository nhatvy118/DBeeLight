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
        return f"""You are a router. Choose the best agent to handle the user request.

Available agents: {agent_list}.

When in doubt about database/export, prefer "database" agent.

Reply with ONLY the agent id, nothing else."""

    async def _route(self, query: str) -> str:
        """Decide which agent should handle this query. Returns agent_id."""
        logger.info(f"[Orchestrator] Routing query: {query[:100]}...")
        if len(self._agents) == 1:
            agent_id = next(iter(self._agents.keys()))
            logger.info(f"[Orchestrator] Only one agent available: {agent_id}")
            return agent_id
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
            agent_id = next(iter(self._agents.keys()))
            logger.info(f"[Orchestrator] No choice from router, default to: {agent_id}")
            return agent_id
        agent_id = choice.message.content.strip().lower().split()[0] if choice.message.content else ""
        final_agent = agent_id if agent_id in self._agents else next(iter(self._agents.keys()))
        logger.info(f"[Orchestrator] Router chose: {agent_id} -> final: {final_agent}")
        return final_agent

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

    async def execute_sql(self, sql: str, lang: str = "en") -> str:
        """
        Execute a raw SQL statement against the database using the database MCP server.

        This is used after the UI shows the planned SQL to the user and the user
        explicitly confirms execution (e.g. by clicking an Execute button).

        Args:
            sql: SQL statement to execute
            lang: Language code for translating response ("en" or "vi")
        """
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        # Prefer execute_query since it can handle both read and write statements.
        # Fall back to run_mutation if needed.
        for server_name, session in db_agent.sessions.items():
            # Try execute_query first
            try:
                result = await session.call_tool("execute_query", {"query": sql})
                result_content = result.content
                # FastMCP usually returns a TextContent object or a list; unwrap to plain text
                try:
                    # Single content object with .text
                    if hasattr(result_content, "text"):
                        result_text = str(result_content.text)
                    # List of content blocks
                    elif isinstance(result_content, list) and result_content:
                        first = result_content[0]
                        if hasattr(first, "text"):
                            result_text = str(first.text)
                        else:
                            result_text = str(result_content)
                    else:
                        result_text = str(result_content)
                except Exception:
                    result_text = str(result_content)

                # Translate if needed
                return self._translate_message(result_text, lang)
            except Exception:
                # Tool not found or error in this server, try next option
                pass

        # If execute_query is not available, try run_mutation as a fallback for write queries
        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("run_mutation", {"sql": sql})
                result_content = result.content
                try:
                    if hasattr(result_content, "text"):
                        result_text = str(result_content.text)
                    if isinstance(result_content, list) and result_content:
                        first = result_content[0]
                        if hasattr(first, "text"):
                            result_text = str(first.text)
                    else:
                        result_text = str(result_content)
                except Exception:
                    result_text = str(result_content)

                # Translate if needed
                return self._translate_message(result_text, lang)
            except Exception:
                continue

        return "No suitable SQL execution tool (execute_query/run_mutation) found in any connected server"

    def _translate_message(self, text: str, lang: str) -> str:
        """Translate message to the specified language using LLM."""
        if lang != "vi":
            return text

        # Use LLM to translate
        try:
            response = self._openai.chat.completions.create(
                model=self._router_model,
                messages=[
                    {"role": "system", "content": "You are a translator. Translate the following text to Vietnamese. Keep the same formatting (markdown, code blocks, tables). Only translate, do not explain anything."},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
            )
            translated = response.choices[0].message.content
            if translated:
                return translated
        except Exception:
            pass

        # If LLM fails, return original text
        return text

    async def cleanup(self) -> None:
        """Clean up all agents."""
        for agent in self._agents.values():
            await agent.cleanup()
