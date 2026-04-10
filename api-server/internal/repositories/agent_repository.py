from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from mcp_agent import DatabaseAgent, ExcelAgent, SessionManager
from mcp_agent.agents import SupersetAgent
from mcp_agent.orchestration import Orchestrator

logger = logging.getLogger("internal")

# Project root for resolving server paths
_project_root = Path(__file__).resolve().parent.parent.parent.parent


class AgentRepository:
    """
    Repository layer for MCP agents. Builds a HybridOrchestrator per user
    (with one or more agents) so the app can use:
    - LLM-driven approach for simple queries
    - LangGraph workflow for complex queries
    - IntentRouter for query classification
    """

    def __init__(
        self,
        default_servers: Optional[list[str]] = None,
        model: str = "gpt-4o-mini",
    ):
        self._default_servers = default_servers or [
            "database/database.py",
            "excel-summary/excel_summary.py",
            "superset/superset_tools.py",
        ]
        # Which servers each agent connects to (agent_id -> list of server path suffixes)
        self._agent_servers: dict[str, list[str]] = {
            "database": ["database/database.py"],
            "excel": ["excel-summary/excel_summary.py"],
            "superset": ["superset/superset_tools.py"],
        }
        self._model = model
        self._db_pool = None

        # Per-user orchestrators (each has its own SessionManager and agents)
        self._orchestrators: dict[str, Orchestrator] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_db_pool(self, db_pool) -> None:
        self._db_pool = db_pool

    def _user_lock(self, user_key: str) -> asyncio.Lock:
        if user_key not in self._locks:
            self._locks[user_key] = asyncio.Lock()
        return self._locks[user_key]

    async def get_agent(self, user_key: str = "anonymous") -> Orchestrator:
        """
        Get or create a hybrid orchestrator for the user.
        Each user gets their own SessionManager and agents (orchestrator).

        The HybridOrchestrator will:
        - Classify query using IntentRouter
        - Use LLM-driven approach for simple queries
        - Use LangGraph workflow for complex queries
        """
        user_key = (user_key or "anonymous").strip() or "anonymous"

        async with self._user_lock(user_key):
            existing = self._orchestrators.get(user_key)
            if existing is not None and existing.sessions:
                return existing

            if user_key != "anonymous" and self._db_pool is None:
                raise RuntimeError("Database pool is not initialized. Sessions require Postgres storage.")

            logger.info("Initializing hybrid orchestrator...")
            session_manager = SessionManager(
                db_pool=self._db_pool,
                user_id=user_key,
                summarize_model=self._model,
            )
            db_agent = DatabaseAgent(model=self._model, session_manager=session_manager, agent_id="database")
            excel_agent = ExcelAgent(model=self._model, session_manager=session_manager, agent_id="excel")
            superset_agent = SupersetAgent(model=self._model, session_manager=session_manager, agent_id="superset")
            agents = [db_agent, excel_agent, superset_agent]

            base_path = _project_root
            connected_count = 0
            for agent in agents:
                server_paths = self._agent_servers.get(agent.agent_id, [])
                for rel in server_paths:
                    full_path = base_path / rel
                    logger.info(f"Checking server: {full_path} (exists: {full_path.exists()})")
                    if not full_path.exists():
                        logger.warning(f"Server not found: {full_path}")
                        continue
                    server_name = full_path.stem
                    try:
                        logger.info(f"Attempting to connect {agent.agent_id} to {server_name} at {full_path}")
                        await agent.connect_to_server(server_name, str(full_path))
                        connected_count += 1
                        logger.info(f"{agent.agent_id} connected to {server_name}")
                    except Exception as e:
                        logger.exception(f"Failed to connect {agent.agent_id} to {server_name}: {e}")

            if connected_count == 0:
                raise RuntimeError(
                    f"No MCP servers connected. Checked paths: {[base_path / sp for sp in self._default_servers]}"
                )

            orchestrator = Orchestrator(
                agents=agents,
                session_manager=session_manager,
                router_model=self._model,
            )
            # Don't create session automatically - session will be created when user sends first message
            logger.info(f"HybridOrchestrator initialized with {connected_count} server(s), {len(agents)} agents")
            for agent in agents:
                logger.info(f"  {agent.agent_id} sessions: {list(agent.sessions.keys())}")

            self._orchestrators[user_key] = orchestrator
            return orchestrator
