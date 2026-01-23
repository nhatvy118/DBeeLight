from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

# Add mcp-client to import path (repo root -> mcp-client/)
_project_root = Path(__file__).resolve().parent.parent.parent.parent
_mcp_client_path = _project_root / "mcp-client"
if str(_mcp_client_path) not in sys.path:
    sys.path.insert(0, str(_mcp_client_path))

from agent import DatabaseAgent, SessionManager  # noqa: E402

logger = logging.getLogger("internal")


class AgentRepository:
    """
    Repository layer for the MCP DatabaseAgent (lifecycle + calls).
    """

    def __init__(
        self,
        default_servers: Optional[list[str]] = None,
        model: str = "gpt-4o-mini",
    ):
        self._default_servers = default_servers or ["database/database.py", "excel-summary/excel_summary.py"]
        self._model = model

        # Per-user agents (so each user has isolated SessionManager/history)
        self._agents: dict[str, DatabaseAgent] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _user_lock(self, user_key: str) -> asyncio.Lock:
        if user_key not in self._locks:
            self._locks[user_key] = asyncio.Lock()
        return self._locks[user_key]

    async def get_agent(self, user_key: str = "anonymous") -> DatabaseAgent:
        """
        Get or create an agent for a given user.

        Each user gets their own SessionManager directory so chat history/sessions are isolated.
        """
        user_key = (user_key or "anonymous").strip() or "anonymous"

        existing = self._agents.get(user_key)
        if existing is not None and existing.sessions:
            return existing

        async with self._user_lock(user_key):
            existing = self._agents.get(user_key)
            if existing is not None and existing.sessions:
                return existing

            logger.info("Initializing DatabaseAgent...")
            # Store sessions per-user under api-server/sessions/<user_key>
            sessions_dir = str((_project_root / "api-server" / "sessions" / user_key).resolve())
            session_manager = SessionManager(sessions_dir=sessions_dir)
            agent = DatabaseAgent(model=self._model, session_manager=session_manager)

            connected_count = 0
            base_path = _project_root
            logger.info(f"Project root: {base_path}")
            logger.info(f"Looking for servers: {self._default_servers}")

            for rel in self._default_servers:
                full_path = base_path / rel
                logger.info(f"Checking server: {full_path} (exists: {full_path.exists()})")
                if not full_path.exists():
                    logger.warning(f"⚠️  Server not found: {full_path}")
                    continue

                server_name = full_path.stem
                try:
                    logger.info(f"Attempting to connect to {server_name} at {full_path}")
                    await agent.connect_to_server(server_name, str(full_path))
                    connected_count += 1
                    logger.info(f"✅ Connected to {server_name}")
                except Exception as e:
                    logger.exception(f"❌ Failed to connect to {server_name}: {e}")

            if connected_count == 0:
                raise RuntimeError(
                    f"No MCP servers connected. Checked paths: {[base_path / sp for sp in self._default_servers]}"
                )

            session_manager.create_session()
            logger.info(f"✅ Agent initialized with {connected_count} server(s) connected")
            logger.info(f"Agent sessions: {list(agent.sessions.keys())}")

            self._agents[user_key] = agent
            return agent

