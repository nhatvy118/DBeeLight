from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from mcp_agent import DatabaseAgent, ExcelAgent, SessionManager, server_script
from mcp_agent.agents import ChartAgent
from mcp_agent.orchestration import Orchestrator

logger = logging.getLogger("internal")

# api-server owns the SQLite data directories. Pass them explicitly to the
# chart-server subprocess so it doesn't have to guess workspace layout.
# - ``internal/databases/`` is where ``sqlite_helper.generate_sqlite_db_path``
#   creates project DBs.
# - ``temp_dbs/`` is for per-session file imports.
# - ``databases/`` (legacy) kept for any projects rowed before the move.
_API_SERVER_ROOT = Path(__file__).resolve().parents[3]
_CHART_SQLITE_ALLOWED_DIRS = ":".join(
    str((_API_SERVER_ROOT / name).resolve())
    for name in ("internal/databases", "temp_dbs", "databases")
)


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
        model: str = "gpt-5.2",
    ):
        # Which bundled MCP servers each agent connects to.
        self._agent_servers: dict[str, list[str]] = {
            "database": ["database"],
            "excel": ["excel"],
            "chart": ["chart"],
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
            chart_agent = ChartAgent(model=self._model, session_manager=session_manager, agent_id="chart")
            agents = [db_agent, excel_agent, chart_agent]

            connected_count = 0
            attempted_paths: list[str] = []
            for agent in agents:
                for server_id in self._agent_servers.get(agent.agent_id, []):
                    full_path = server_script(server_id)
                    attempted_paths.append(str(full_path))
                    logger.info(f"Checking server: {full_path} (exists: {full_path.exists()})")
                    if not full_path.exists():
                        logger.warning(f"Server not found: {full_path}")
                        continue
                    # Inject per-server env.
                    extra_env: dict[str, str] = {}
                    if server_id == "chart":
                        # chart-server validates that incoming SQLite db_urls
                        # live under one of these dirs (defense in depth).
                        extra_env["CHART_SQLITE_ALLOWED_DIRS"] = _CHART_SQLITE_ALLOWED_DIRS
                    try:
                        logger.info(f"Attempting to connect {agent.agent_id} to {server_id} at {full_path}")
                        await agent.connect_to_server(server_id, str(full_path), env=extra_env)
                        connected_count += 1
                        logger.info(f"{agent.agent_id} connected to {server_id}")
                    except Exception as e:
                        logger.exception(f"Failed to connect {agent.agent_id} to {server_id}: {e}")

            if connected_count == 0:
                raise RuntimeError(
                    f"No MCP servers connected. Checked paths: {attempted_paths}"
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
