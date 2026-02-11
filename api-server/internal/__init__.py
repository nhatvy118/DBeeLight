"""
FastAPI Server để kết nối Frontend với MCP Agent

This package is structured into 3 layers:
- controllers: FastAPI routers + request/response schemas
- usecases: business logic
- repositories: IO / external integrations (MCP agent, Google OAuth, etc.)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from internal.controllers import auth_controller, chat_controller, health_controller, project_controller, sessions_controller, share_controller
from internal.db import close_db, init_db
from internal.utils.redis_client import close_redis_client, init_redis_client

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("internal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    await init_db(app)
    await init_redis_client()
    yield
    # Shutdown
    await close_db(app)
    await close_redis_client()


def create_app() -> FastAPI:
    app = FastAPI(
        title="MCP API Server",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Session cookie (used for OAuth login state + user session)
    # IMPORTANT: set SESSION_SECRET in production.
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.getenv("SESSION_SECRET", "dev-session-secret-change-me"),
        same_site="lax",
        https_only=bool(os.getenv("SESSION_HTTPS_ONLY", "").strip()),
    )

    # CORS
    # If you use cookies cross-origin, allow_origins must NOT be "*".
    cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers (dependencies are provided via internal/dependencies.py)
    app.include_router(health_controller.router)
    app.include_router(auth_controller.router)
    app.include_router(chat_controller.router)
    app.include_router(sessions_controller.router)
    app.include_router(project_controller.router)
    app.include_router(share_controller.router)

    return app


app = create_app()


def main():
    """Entry point for running the server."""
    port = int(os.getenv("PORT", "5001"))
    logger.info(f"Starting FastAPI server on port {port}")
    uvicorn.run("internal:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()

