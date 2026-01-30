from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from mcp_agent import DatabaseAgent, SessionManager

logger = logging.getLogger("internal")

# Project root for resolving server paths
_project_root = Path(__file__).resolve().parent.parent.parent.parent


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
        self._db_pool = None

        # Per-user agents (so each user has isolated SessionManager/history)
        self._agents: dict[str, DatabaseAgent] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_db_pool(self, db_pool) -> None:
        self._db_pool = db_pool

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

            if self._db_pool is None:
                raise RuntimeError("Database pool is not initialized. Sessions require Postgres storage.")

            logger.info("Initializing DatabaseAgent...")
           
            # Khởi tạo SessionManager không gắn với project cụ thể (project_id=None).
            session_manager = SessionManager(db_pool=self._db_pool, user_id=user_key)
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

            await session_manager.create_session()
            logger.info(f"✅ Agent initialized with {connected_count} server(s) connected")
            logger.info(f"Agent sessions: {list(agent.sessions.keys())}")

            self._agents[user_key] = agent
            return agent

