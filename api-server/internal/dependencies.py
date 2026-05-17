"""Cross-cutting FastAPI dependencies.

Each feature owns its own ``dependencies.py``. Import feature deps directly
from there — this module only hosts truly cross-cutting helpers (current
user, Redis client, etc.) so it does not need to know about every feature.
"""

from __future__ import annotations

from fastapi import Request

from internal.infra.redis import get_redis_client


def get_user_key(request: Request) -> str:
    """Stable per-user key for chat history isolation.

    - Logged-in users: Google ``sub``
    - Otherwise: ``"anonymous"``
    """
    user = request.session.get("user") if hasattr(request, "session") else None
    if isinstance(user, dict):
        sub = user.get("sub")
        if isinstance(sub, str) and sub.strip():
            return sub.strip()
    return "anonymous"


async def get_redis_client_dependency() -> object:
    """Returns Redis client or ``None`` if not available."""
    return await get_redis_client()
