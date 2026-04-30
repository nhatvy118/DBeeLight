"""Progress event emitter using contextvars.

Workflows call ``emit(stage, status, message)`` at key points; the chat-stream
HTTP handler sets a ContextVar to a callback that pushes events into an SSE
queue. When no callback is set (the default ``/api/chat`` endpoint), emit() is
a no-op — no behavior change for non-streaming callers.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# A callback that takes a progress event dict and returns nothing.
ProgressCallback = Callable[[dict], Awaitable[None]]

_progress_callback_var: contextvars.ContextVar[Optional[ProgressCallback]] = (
    contextvars.ContextVar("progress_callback", default=None)
)


def set_progress_callback(cb: Optional[ProgressCallback]) -> contextvars.Token:
    """Bind a progress callback for the current async context. Returns a
    Token that can be passed to ``reset_progress_callback`` to restore."""
    return _progress_callback_var.set(cb)


def reset_progress_callback(token: contextvars.Token) -> None:
    _progress_callback_var.reset(token)


async def emit(
    stage: str,
    status: str = "running",
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    """Push a progress event to the chat-stream callback if one is bound.

    Args:
        stage: Stage identifier (e.g. ``"DB_CONNECTION"``)
        status: ``"running"`` | ``"completed"`` | ``"error"``
        message: Human-readable label (Vietnamese OK)
        **extra: Additional fields merged into the event payload
    """
    cb = _progress_callback_var.get()
    if cb is None:
        return
    event = {"type": "stage", "stage": stage, "status": status}
    if message is not None:
        event["message"] = message
    if extra:
        event.update(extra)
    try:
        await cb(event)
    except Exception as e:
        # Never let a misbehaving callback break the workflow
        logger.warning(f"[progress.emit] callback raised: {e}")
