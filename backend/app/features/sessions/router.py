"""Sessions router. A session may be global (project_id=null) or tied to a project."""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.features.auth.deps import get_current_user_id
from app.features.projects import repository as proj_repo
from app.features.sessions import repository as repo

logger = logging.getLogger("features.sessions.router")

router = APIRouter(tags=["sessions"])


@router.post("/api/sessions")
async def create(body: dict, user_id: str = Depends(get_current_user_id)):
    logger.info("→ create(body=%r user_id=%r)", body, user_id)  # autolog
    project_id = body.get("project_id") or None
    if project_id and not await proj_repo.get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Project does not exist / not yours")
    s = await repo.create_session(user_id, project_id, body.get("name") or "New chat")
    info = {"session_id": s["id"], "session_name": s["title"], "project_id": s["project_id"]}
    return {"success": True, "session_id": s["id"], "session_info": info}


@router.get("/api/sessions")
async def list_all(
    project_id: str | None = None, unassigned_only: bool = False,
    user_id: str = Depends(get_current_user_id),
):
    logger.info("→ list_all(project_id=%r unassigned_only=%r user_id=%r)", project_id, unassigned_only, user_id)  # autolog
    rows = await repo.list_sessions(user_id, project_id, unassigned_only)
    return {"success": True, "sessions": [
        {"session_id": r["id"], "session_name": r["title"], "project_id": r["project_id"]} for r in rows
    ]}


@router.get("/api/sessions/{session_id}")
async def get_one(session_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ get_one(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    s = await repo.get_session(session_id, user_id)
    if not s:
        return {"success": False, "error": "not found"}
    msgs = await repo.get_history(session_id)
    return {
        "success": True,
        "session_info": {"session_id": s["id"], "session_name": s["title"], "project_id": s["project_id"]},
        "messages": [{"role": m["role"], "content": m["content"],
                      "tool_events": m.get("tool_events") or [], "pending_workflow_resume": False}
                     for m in msgs],
        "share_info": None,
    }


@router.delete("/api/sessions/{session_id}")
async def delete(session_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ delete(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    from app.db import get_pool
    await get_pool().execute(
        "DELETE FROM sessions WHERE id=$1 AND user_id=$2", session_id, user_id
    )
    return {"success": True}


@router.get("/api/sessions/{session_id}/messages")
async def history(session_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ history(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    if not await repo.get_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return [{"role": m["role"], "content": m["content"], "tool_events": m.get("tool_events") or []}
            for m in await repo.get_history(session_id)]


@router.get("/api/sessions/{session_id}/export.md")
async def export_md(session_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ export_md(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    from fastapi.responses import Response

    s = await repo.get_session(session_id, user_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    lines = [f"# {s['title']}\n"]
    for m in await repo.get_history(session_id):
        who = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"## {who}\n\n{m['content']}\n")
    md = "\n".join(lines)
    return Response(content=md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{session_id}.md"'})
