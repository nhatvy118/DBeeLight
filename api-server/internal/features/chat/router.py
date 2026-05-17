from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from internal.dependencies import get_user_key
from internal.features.chat.dependencies import get_chat_service
from internal.features.chat.schema import (
    ChatOk,
    ChatRequest,
    ExecuteSqlRequest,
    WorkflowResumeRequest,
)
from internal.features.chat.service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ChatOk)
async def chat(
    req: ChatRequest,
    user_key: str = Depends(get_user_key),
    service: ChatService = Depends(get_chat_service),
) -> ChatOk:
    response_text, sid, tool_events, pending, warnings, success = await service.chat(
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
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Streaming variant of ``/api/chat`` (Server-Sent Events)."""
    generator = service.chat_stream(
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
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/chat/workflow-resume", response_model=ChatOk)
async def workflow_resume(
    req: WorkflowResumeRequest,
    user_key: str = Depends(get_user_key),
    service: ChatService = Depends(get_chat_service),
) -> ChatOk:
    response_text, sid, tool_events, pending, warnings, success = await service.workflow_resume(
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
    service: ChatService = Depends(get_chat_service),
) -> ChatOk:
    """Execute a raw SQL statement that has already been previewed to the user."""
    response_text, sid, tool_events, pending, warnings, success = await service.execute_sql(
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
