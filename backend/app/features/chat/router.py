"""Chat router — POST /api/chat streams SSE; POST /api/chat/resume for approval.

SSE frames: `data: {"type": "stage"|"final"|"error", ...}\\n\\n`. The terminal
`final` frame carries `data` = ChatResponse. Per-request ContextVar wiring + history
persistence live in ChatService; db_url is resolved server-side.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.features.auth.deps import get_current_user_id
from app.features.chat import service
from app.features.chat.schema import ChatRequest, ResumeRequest
from app.features.sessions import repository as sess_repo

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _frame(obj: dict) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


def _map_tool_events(events: list[dict]) -> list[dict]:
    out = []
    for e in events or []:
        if e.get("type") and e.get("payload") is not None:
            out.append(e)
            continue
        out.append({
            "tool": e.get("tool", ""),
            "type": "sql_execution" if e.get("tool") == "execute_query" else "tool_result",
            "payload": {"sql": (e.get("args") or {}).get("query"), "result": e.get("result")},
        })
    return out


def _response(result, session_id: str) -> dict:
    return {
        "success": True,
        "response": result.response,
        "session_id": session_id,
        "route": result.route,
        "requires_approval": bool(result.requires_approval),
        "pending_workflow_resume": bool(result.requires_approval),
        "needs_clarification": bool(getattr(result, "needs_clarification", False)),
        "tool_events": _map_tool_events(getattr(result, "tool_events", [])),
    }


async def _get_or_create_session(user_id: str, session_id: str | None, project_id: str | None) -> str:
    """Return an owned session id: reuse the given one if it exists & belongs to the user,
    otherwise create a fresh "New chat" (title is auto-named from the first message later)."""
    if session_id and await sess_repo.get_session(session_id, user_id):
        return session_id
    s = await sess_repo.create_session(user_id, project_id or None, "New chat")
    return s["id"]


@router.post("")
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user_id)):
    session_id = await _get_or_create_session(user_id, req.session_id, req.project_id)

    async def gen():
        yield _frame({"type": "stage", "message": "Processing"})
        try:
            result = await service.handle(user_id, session_id, req.message, req.active_file_ids)
        except service.ChatError as e:
            yield _frame({"type": "error", "status_code": 400, "message": str(e)})
            return
        except Exception as e:
            yield _frame({"type": "error", "status_code": 500, "message": str(e)})
            return
        yield _frame({"type": "final", "data": _response(result, session_id)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/resume")
async def resume(req: ResumeRequest, user_id: str = Depends(get_current_user_id)):
    try:
        result = await service.approve(user_id, req.session_id, req.approved, edited_schema=req.edited_schema)
    except service.ChatError as e:
        return {"success": False, "error": str(e)}
    return _response(result, req.session_id)
