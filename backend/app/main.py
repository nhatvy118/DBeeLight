"""FastAPI app + lifespan.

Lifespan builds: app DB pool (metadata), ConnectionPool (singleton), Orchestrator
(singleton, warmup excel). NO per-user subprocess spawning.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.agent.orchestration import get_orchestrator
from app.agent.pool import get_connection_pool
from pathlib import Path

from app.config import get_settings
from app.db import close_pool, init_pool, run_migrations
from app.features.admin.router import router as admin_router
from app.features.auth.router import router as auth_router
from app.features.charts.router import router as charts_router
from app.features.chat.router import router as chat_router
from app.features.files.router import router as files_router
from app.features.projects.router import router as projects_router
from app.features.sessions.router import router as sessions_router
from app.logging_config import setup_logging

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    s = get_settings()
    try:
        await init_pool(s.database_url)
        logger.info("App DB pool ready.")
        try:
            await run_migrations(Path(__file__).resolve().parent.parent / "migrations")
            logger.info("Migrations applied.")
        except Exception as e:  # noqa: BLE001
            logger.warning("Running migrations failed: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not connect to app DB (%s) — metadata APIs will fail until Postgres is available.", e)

    orch = get_orchestrator()
    await orch.warmup()
    logger.info("Orchestrator singleton ready.")
    yield

    await get_connection_pool().close_all()
    await close_pool()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="DBeeLight Backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_list,
        allow_credentials=True,   # needed for cookie session (FE credentials:'include')
        allow_methods=["*"],
        allow_headers=["*"],
    )
    same_site = s.session_same_site.lower().strip()
    if same_site not in ("lax", "strict", "none"):
        same_site = "lax"
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.session_secret,
        same_site=cast(Literal["lax", "strict", "none"], same_site),
        https_only=s.session_https_only,
    )
    app.include_router(auth_router)       # /api/auth/* (cookie session)
    app.include_router(projects_router)   # /api/projects/* (incl. external-DB projects)
    app.include_router(charts_router)     # /api/projects/{id}/charts, /dashboard/render
    app.include_router(sessions_router)   # /api/sessions/*
    app.include_router(files_router)      # /api/files/*
    app.include_router(admin_router)      # /api/admin/*
    app.include_router(chat_router)       # /api/chat, /api/chat/approve

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "agent_initialized": True}

    return app


app = create_app()
