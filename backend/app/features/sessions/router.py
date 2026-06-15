"""Sessions router. A session may be global (project_id=null) or tied to a project."""
from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException

from app.features.auth.deps import get_current_user_id
from app.features.projects import repository as proj_repo
from app.features.sessions import repository as repo
from app.features.sessions import service

router = APIRouter(tags=["sessions"])


@router.post("/api/sessions")
async def create(body: dict, user_id: str = Depends(get_current_user_id)):
    project_id = body.get("project_id") or None
    if project_id and not await proj_repo.get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Project does not exist / not yours")
    s = await repo.create_session(user_id, project_id, "New chat")
    info = {
        "session_id": s["id"], "session_name": s["title"], "project_id": s["project_id"],
        **await service.db_descriptor(user_id, s),
    }
    return {"success": True, "session_id": s["id"], "session_info": info}


@router.get("/api/sessions")
async def list_all(
    project_id: str | None = None, unassigned_only: bool = False,
    user_id: str = Depends(get_current_user_id),
):
    rows = await repo.list_sessions(user_id, project_id, unassigned_only)
    return {"success": True, "sessions": [
        {"session_id": r["id"], "session_name": r["title"], "project_id": r["project_id"]} for r in rows
    ]}


@router.get("/api/sessions/{session_id}")
async def get_one(session_id: str, user_id: str = Depends(get_current_user_id)):
    """Session metadata only. Messages are loaded separately (cursor-paginated) via /messages."""
    s = await repo.get_session(session_id, user_id)
    if not s:
        return {"success": False, "error": "not found"}
    return {
        "success": True,
        "session_info": {
            "session_id": s["id"], "session_name": s["title"], "project_id": s["project_id"],
            **await service.db_descriptor(user_id, s),
        },
        "share_info": None,
    }


@router.get("/api/sessions/{session_id}/messages")
async def messages(
    session_id: str,
    before: str | None = None,
    limit: int = 30,
    user_id: str = Depends(get_current_user_id),
):
    """Cursor-paginated messages (newest-first window, returned oldest→newest).
    `before` = next_cursor from a previous page (load older on scroll-up); omit for the latest page."""
    if not await repo.get_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    page = await repo.get_messages(session_id, limit=min(max(limit, 1), 100), before=before)
    return {"success": True, **page}


@router.delete("/api/sessions/{session_id}")
async def delete(session_id: str, user_id: str = Depends(get_current_user_id)):
    await repo.delete_session(session_id, user_id)
    return {"success": True}


@router.get("/api/sessions/{session_id}/export.md")
async def export_md(session_id: str, user_id: str = Depends(get_current_user_id)):
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
