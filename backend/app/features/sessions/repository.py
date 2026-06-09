from __future__ import annotations

import json
import uuid

from app.db import get_pool


async def create_session(user_id: str, project_id: str | None, title: str) -> dict:
    """project_id=None → global session (not tied to a project).

    Session id is a SHORT dash-less hex so the frontend can distinguish a session
    (short, no '-') from a project (full UUID with '-') by URL format.
    """
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
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, project_id, title FROM sessions WHERE id=$1 AND user_id=$2",
        session_id, user_id,
    )
    return dict(row) if row else None


async def add_message(session_id: str, role: str, content: str, tool_events: list[dict] | None = None) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO messages (id, session_id, role, content, tool_events)
        VALUES ($1, $2, $3, $4, $5)
        """,
        str(uuid.uuid4()), session_id, role, content, json.dumps(tool_events or []),
    )


async def get_history(session_id: str, limit: int = 40) -> list[dict]:
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
