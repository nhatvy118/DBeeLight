"""Per-request context (task-local) — replaces the old module globals.

Each HTTP request runs in its own asyncio Task → each Task has its own ContextVar
copy. So two concurrent users do NOT clobber each other's connection/identity.

The LLM never sees what is here: the adapter is injected into tools via the ContextVar,
not via tool arguments.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.agent.adapters.base import DatabaseAdapter


@dataclass
class DbContext:
    """Connection scope of a request."""

    primary: Optional["DatabaseAdapter"] = None      # project DB (the only queryable source)
    engine: str = "postgresql"                        # 'sqlite' | 'postgresql' (cho dialect rules)


@dataclass
class RequestContext:
    """All per-request state (identity + db). Nothing lives on the singleton instance."""

    user_id: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    db: DbContext = field(default_factory=DbContext)


_current_ctx: ContextVar[RequestContext] = ContextVar("current_ctx")


def set_ctx(ctx: RequestContext):
    """Inject context for the current request. Returns a token to reset in finally."""
    return _current_ctx.set(ctx)


def reset_ctx(token) -> None:
    _current_ctx.reset(token)


def get_ctx() -> RequestContext:
    try:
        return _current_ctx.get()
    except LookupError:
        raise RuntimeError("RequestContext has not been set for this request.")


def get_db() -> DbContext:
    return get_ctx().db
