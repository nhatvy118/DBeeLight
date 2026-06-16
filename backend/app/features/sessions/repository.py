from __future__ import annotations
import logging

import json
import uuid

from app.db import get_pool

logger = logging.getLogger("features.sessions.repository")


async def create_session(user_id: str, project_id: str | None, title: str) -> dict:
    """project_id=None → global session (not tied to a project).

    Session id is a SHORT dash-less hex so the frontend can distinguish a session
    (short, no '-') from a project (full UUID with '-') by URL format.
    """
    logger.info("→ create_session(user_id=%r project_id=%r title=%r)", user_id, project_id, title)  # autolog
    pool = get_pool()
    sid = uuid.uuid4().hex[:12]
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (id, user_id, project_id, title)
        VALUES ($1, $2, $3, $4)
        RETURNING id, project_id, title
        """,
        sid, user_id, project_id, title,
    )
    return dict(row)


async def list_sessions(
    user_id: str, project_id: str | None = None, unassigned_only: bool = False
) -> list[dict]:
    logger.info("→ list_sessions(user_id=%r project_id=%r unassigned_only=%r)", user_id, project_id, unassigned_only)  # autolog
    pool = get_pool()
    if unassigned_only:
        rows = await pool.fetch(
            "SELECT id, project_id, title FROM sessions WHERE user_id=$1 AND project_id IS NULL "
            "ORDER BY created_at DESC",
            user_id,
        )
    elif project_id:
        rows = await pool.fetch(
            "SELECT id, project_id, title FROM sessions WHERE user_id=$1 AND project_id=$2 "
            "ORDER BY created_at DESC",
            user_id, project_id,
        )
    else:
        rows = await pool.fetch(
            "SELECT id, project_id, title FROM sessions WHERE user_id=$1 ORDER BY created_at DESC",
            user_id,
        )
    return [dict(r) for r in rows]


async def get_session(session_id: str, user_id: str) -> dict | None:
    """Full session row (ownership-scoped). Callers read whichever fields they need."""
    logger.info("→ get_session(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, user_id, project_id, title, share_recipient_id, created_at "
        "FROM sessions WHERE id=$1 AND user_id=$2",
        session_id, user_id,
    )
    return dict(row) if row else None


async def set_sql_action(session_id: str, action_id: str, state: str) -> None:
    """Record a gated SQL action's outcome (executed/cancelled/failed) so the Execute
    button state survives a history reload."""
    logger.info("→ set_sql_action(session_id=%r action_id=%r state=%r)", session_id, action_id, state)  # autolog
    pool = get_pool()
    await pool.execute(
        "INSERT INTO sql_actions (session_id, action_id, state) VALUES ($1, $2, $3) "
        "ON CONFLICT (session_id, action_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
        session_id, action_id, state,
    )


async def get_sql_actions(session_id: str) -> dict:
    pool = get_pool()
    rows = await pool.fetch("SELECT action_id, state FROM sql_actions WHERE session_id = $1", session_id)
    return {r["action_id"]: r["state"] for r in rows}


async def delete_session(session_id: str, user_id: str) -> None:
    """Delete a session (ownership-scoped). Its messages cascade via FK ON DELETE CASCADE."""
    logger.info("→ delete_session(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    pool = get_pool()
    await pool.execute(
        "DELETE FROM sessions WHERE id=$1 AND user_id=$2", session_id, user_id
    )


async def set_title(session_id: str, user_id: str, title: str) -> None:
    """Update a session's title (ownership-scoped). Used to auto-name from the first message."""
    logger.info("→ set_title(session_id=%r user_id=%r title=%r)", session_id, user_id, title)  # autolog
    pool = get_pool()
    await pool.execute(
        "UPDATE sessions SET title=$3 WHERE id=$1 AND user_id=$2",
        session_id, user_id, title,
    )


async def add_message(session_id: str, role: str, content: str, tool_events: list[dict] | None = None) -> None:
    logger.info("→ add_message(session_id=%r role=%r content=%r tool_events=%r)", session_id, role, content, tool_events)  # autolog
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO messages (id, session_id, role, content, tool_events)
        VALUES ($1, $2, $3, $4, $5)
        """,
        str(uuid.uuid4()), session_id, role, content, json.dumps(tool_events or []),
    )


async def get_history(session_id: str, limit: int = 20) -> list[dict]:
    logger.info("→ get_history(session_id=%r limit=%r)", session_id, limit)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT role, content, tool_events FROM messages WHERE session_id=$1 "
        "ORDER BY created_at ASC LIMIT $2",
        session_id, limit,
    )
    out = []
    for r in rows:
        d = dict(r)
        te = d.get("tool_events")
        d["tool_events"] = json.loads(te) if isinstance(te, str) else (te or [])
        out.append(d)
    return out


def _row_to_message(r) -> dict:
    d = dict(r)
    te = d.get("tool_events")
    return {
        "id": d["id"],
        "role": d["role"],
        "content": d["content"],
        "tool_events": json.loads(te) if isinstance(te, str) else (te or []),
        "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
    }


async def get_messages(session_id: str, limit: int = 30, before: str | None = None) -> dict:
    """Cursor-paginated messages for the chat UI.

    Returns the newest `limit` messages older than `before` (an ISO created_at; None = latest),
    ordered oldest→newest for rendering. `next_cursor` is the created_at of the oldest message
    returned — pass it back as `before` to load the previous (older) page on scroll-up.
    """
    logger.info("→ get_messages(session_id=%r limit=%r before=%r)", session_id, limit, before)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, role, content, tool_events, created_at FROM messages "
        "WHERE session_id=$1 AND ($2::timestamptz IS NULL OR created_at < $2::timestamptz) "
        "ORDER BY created_at DESC LIMIT $3",
        session_id, before, limit + 1,  # fetch one extra to detect older pages
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = [_row_to_message(r) for r in reversed(rows)]  # DESC → reverse to oldest→newest
    next_cursor = messages[0]["created_at"] if (messages and has_more) else None
    return {"messages": messages, "has_more": has_more, "next_cursor": next_cursor}
