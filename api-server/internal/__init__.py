"""FastAPI Server kết nối Frontend với MCP Agent.

Feature-based layout under ``internal/features/<feature>/``:
- ``router.py``      — FastAPI router (HTTP-only)
- ``service.py``     — business logic
- ``repository.py``  — DB / external IO
- ``schema.py``      — Pydantic request/response
- ``dependencies.py``— ``Depends()`` chain for this feature
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

from internal.features.admin.router import router as admin_router
from internal.features.auth.router import router as auth_router
from internal.features.chat.router import router as chat_router
from internal.features.file.router import router as file_router
from internal.features.health.router import router as health_router
from internal.features.project.router import router as project_router
from internal.features.sessions.router import router as sessions_router
from internal.features.share.router import router as share_router
from internal.infra.database import close_db, init_db
from internal.infra.redis import close_redis_client, init_redis_client

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
    try:
        from internal.features.chat.dependencies import _agent_repository_singleton
        await _agent_repository_singleton().shutdown()
    except Exception as e:
        logger.warning("Agent repository shutdown failed: %s", e)
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
    # Frontend and API share the same site (e.g. www.* and api.* under the same
    # registrable domain), so SameSite=Lax + Secure is enough — the cookie is sent
    # on cross-subdomain /api/* requests. Override via env only if you move the
    # frontend to a different site (then use SameSite=None + Secure).
    session_same_site = os.getenv("SESSION_SAME_SITE", "lax").lower()
    session_https_only = bool(os.getenv("SESSION_HTTPS_ONLY", "").strip())
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.getenv("SESSION_SECRET", "dev-session-secret-change-me"),
        same_site=session_same_site,
        https_only=session_https_only,
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

    # Feature routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(file_router)
    app.include_router(sessions_router)
    app.include_router(project_router)
    app.include_router(share_router)
    app.include_router(admin_router)

    return app


app = create_app()


def main():
    """Entry point for running the server."""
    port = int(os.getenv("PORT", "5001"))
    logger.info(f"Starting FastAPI server on port {port}")
    uvicorn.run("internal:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()

