from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from internal.controllers.schemas import (
    ChatOk,
    ChatRequest,
    ExecuteSqlRequest,
    ExportRequest,
    WorkflowResumeRequest,
)  # noqa: F401
from internal.dependencies import get_chat_usecase, get_user_key
from internal.usecases.chat_usecase import ChatUseCase


router = APIRouter()

@router.post("/api/chat", response_model=ChatOk)
async def chat(
    req: ChatRequest,
    user_key: str = Depends(get_user_key),
    usecase: ChatUseCase = Depends(get_chat_usecase),
) -> ChatOk:
    response_text, sid, tool_events, pending, warnings, success = await usecase.chat(
        user_key, req.message, req.session_id, req.project_id
    )
    return ChatOk(
        success=success,
        response=response_text,
        session_id=sid,
        warnings=warnings,
        tool_events=tool_events,
        pending_workflow_resume=pending,
    )


@router.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    user_key: str = Depends(get_user_key),
    usecase: ChatUseCase = Depends(get_chat_usecase),
) -> StreamingResponse:
    """Streaming variant of ``/api/chat``.

    Returns a Server-Sent Events stream:
      event: started        — stream open, chat task launched
      event: stage          — workflow stage progress (running/completed/error)
      event: final          — full chat response (same shape as /api/chat)
      event: error          — terminal error before final

    Frontend should parse with fetch + ReadableStream rather than EventSource
    (EventSource is GET-only).
    """
    generator = usecase.chat_stream(
        user_key=user_key,
        message=req.message,
        session_id=req.session_id,
        project_id=req.project_id,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx response buffering
            "Connection": "keep-alive",
        },
    )


@router.post("/api/chat/workflow-resume", response_model=ChatOk)
async def workflow_resume(
    req: WorkflowResumeRequest,
    user_key: str = Depends(get_user_key),
    usecase: ChatUseCase = Depends(get_chat_usecase),
) -> ChatOk:
    response_text, sid, tool_events, pending, warnings, success = await usecase.workflow_resume(
        user_key,
        req.session_id,
        req.approved,
        req.project_id,
        req.user_visible_message,
    )
    return ChatOk(
        success=success,
        response=response_text,
        session_id=sid,
        warnings=warnings,
        tool_events=tool_events,
        pending_workflow_resume=pending,
    )


@router.post("/api/sql/execute", response_model=ChatOk)
async def execute_sql(
    req: ExecuteSqlRequest,
    user_key: str = Depends(get_user_key),
    usecase: ChatUseCase = Depends(get_chat_usecase),
) -> ChatOk:
    """
    Execute a raw SQL statement that has already been previewed to the user.

    - `sql`: the exact SQL to execute (taken from the last ```sql``` block shown in the UI)
    - `session_id`: optional, to keep history linked to the same conversation
    - `project_id`: optional, to auto-connect to the correct project database
    """
    response_text, sid, tool_events, pending, warnings, success = await usecase.execute_sql(
        user_key,
        req.sql,
        req.action_id,
        req.session_id,
        req.project_id,
        req.lang,
        req.lock_only or False,
        req.lock_state,
    )
    return ChatOk(
        success=success,
        response=response_text,
        session_id=sid,
        warnings=warnings,
        tool_events=tool_events,
        pending_workflow_resume=pending,
    )


