from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from mcp_agent import DatabaseAgent, ExcelAgent, SessionManager, server_script
from mcp_agent.agents import ChartAgent
from mcp_agent.orchestration import Orchestrator

logger = logging.getLogger("internal")

# LRU/TTL bounds for the per-user orchestrator cache. Each orchestrator holds
# ~3 MCP subprocesses (~190 MB total), so an unbounded cache leaks RAM as users
# accumulate. We evict idle/least-recently-used orchestrators to cap live
# subprocesses at MAX_ORCHESTRATORS × 3. Evicted users transparently re-init on
# their next request (history lives in Postgres, not the orchestrator).
MAX_ORCHESTRATORS = 5
ORCHESTRATOR_TTL_SECONDS = 600  # evict orchestrators idle longer than 10 minutes
# Never evict (for over-capacity trimming) an orchestrator used within this
# window — guards short in-flight requests that don't hold a refcount.
_EVICT_RECENT_GUARD_SECONDS = 120

# All SQLite data lives under ``api-server/internal/``. Pass these dirs
# explicitly to the chart-server subprocess so it doesn't have to guess the
# workspace layout. These MUST match where the file service actually writes
# (``_internal_data_root()`` in internal/features/file/service.py):
# - ``databases/`` — project DBs from ``sqlite_helper.generate_sqlite_db_path``.
# - ``temp_dbs/``  — per-session file imports.
_INTERNAL_DATA_ROOT = Path(__file__).resolve().parents[2]
_CHART_SQLITE_ALLOWED_DIRS = ":".join(
    str((_INTERNAL_DATA_ROOT / name).resolve())
    for name in ("databases", "temp_dbs")
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
        # LRU/refcount bookkeeping for cache eviction.
        self._last_used: dict[str, float] = {}   # user_key -> monotonic timestamp
        self._inflight: dict[str, int] = {}      # user_key -> active request count

    def set_db_pool(self, db_pool) -> None:
        self._db_pool = db_pool

    def _user_lock(self, user_key: str) -> asyncio.Lock:
        if user_key not in self._locks:
            self._locks[user_key] = asyncio.Lock()
        return self._locks[user_key]

    def mark_in_use(self, user_key: str) -> None:
        """Pin a user's orchestrator while a request is actively using it, so
        the eviction sweep never tears down its subprocesses mid-request."""
        user_key = (user_key or "anonymous").strip() or "anonymous"
        self._inflight[user_key] = self._inflight.get(user_key, 0) + 1
        self._last_used[user_key] = time.monotonic()

    def mark_done(self, user_key: str) -> None:
        """Release a pin set by ``mark_in_use`` (call in a ``finally``)."""
        user_key = (user_key or "anonymous").strip() or "anonymous"
        if user_key in self._inflight:
            self._inflight[user_key] = max(0, self._inflight[user_key] - 1)
        self._last_used[user_key] = time.monotonic()

    def _detach_evictable(self, exclude_user: str) -> list[Orchestrator]:
        """Synchronously (no ``await``) pick + remove orchestrators to evict and
        return them so the caller can ``await cleanup()`` outside any lock.

        Never evicts: the current user, in-use agents (``inflight > 0``), or —
        for over-capacity trimming — agents touched within the recent guard
        window. Idle-past-TTL agents are always evicted. Being await-free, the
        selection is atomic w.r.t. other coroutines on the event loop."""
        now = time.monotonic()
        detached: list[Orchestrator] = []

        def _pop(uk: str) -> Optional[Orchestrator]:
            self._last_used.pop(uk, None)
            self._inflight.pop(uk, None)
            return self._orchestrators.pop(uk, None)

        # 1) Evict anything idle longer than the TTL.
        for uk in list(self._orchestrators.keys()):
            if uk == exclude_user or self._inflight.get(uk, 0) > 0:
                continue
            if now - self._last_used.get(uk, 0.0) > ORCHESTRATOR_TTL_SECONDS:
                orch = _pop(uk)
                if orch is not None:
                    detached.append(orch)

        # 2) Trim to capacity by LRU so adding the current user stays <= MAX.
        while len(self._orchestrators) > MAX_ORCHESTRATORS - 1:
            candidates = [
                uk for uk in self._orchestrators
                if uk != exclude_user
                and self._inflight.get(uk, 0) == 0
                and now - self._last_used.get(uk, 0.0) > _EVICT_RECENT_GUARD_SECONDS
            ]
            if not candidates:
                break  # everyone is busy/recent → allow temporary over-capacity
            lru = min(candidates, key=lambda uk: self._last_used.get(uk, 0.0))
            orch = _pop(lru)
            if orch is not None:
                detached.append(orch)
        return detached

    async def shutdown(self) -> None:
        """Tear down every cached orchestrator (kills all MCP subprocesses).
        Call from the app's lifespan shutdown."""
        orchestrators = list(self._orchestrators.values())
        self._orchestrators.clear()
        self._last_used.clear()
        self._inflight.clear()
        for orch in orchestrators:
            try:
                await orch.cleanup()
            except Exception as e:
                logger.warning("AgentRepository.shutdown: cleanup failed: %s", e)

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
                self._last_used[user_key] = time.monotonic()
                return existing

            if user_key != "anonymous" and self._db_pool is None:
                raise RuntimeError("Database pool is not initialized. Sessions require Postgres storage.")

            # Make room before adding a new orchestrator: evict idle/LRU ones
            # (never the current user, never in-use agents) and kill their
            # subprocesses to free RAM.
            for evicted in self._detach_evictable(exclude_user=user_key):
                try:
                    await evicted.cleanup()
                    logger.info("Evicted an idle orchestrator and cleaned up its subprocesses")
                except Exception as e:
                    logger.warning("Eviction cleanup failed: %s", e)

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
            self._last_used[user_key] = time.monotonic()
            return orchestrator
