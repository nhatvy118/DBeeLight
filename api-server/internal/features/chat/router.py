from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from internal.dependencies import get_user_key
from internal.features.chat.dependencies import get_chat_service
from internal.features.chat.schema import (
    ChatOk,
    ChatRequest,
    DbConnectOk,
    DbConnectRequest,
    ExecuteSqlRequest,
    WorkflowResumeRequest,
)
from internal.features.chat.service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    user_key: str = Depends(get_user_key),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Chat endpoint (Server-Sent Events).

    Emits ``started`` → ``stage`` (progress) → ``final`` events. Callers that
    only need the final payload can wait for ``final``; ``service.chat()`` is
    still the underlying processor and is reused as a single code path."""
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


@router.post("/api/db/connect", response_model=DbConnectOk)
async def db_connect(
    req: DbConnectRequest,
    user_key: str = Depends(get_user_key),
    service: ChatService = Depends(get_chat_service),
) -> DbConnectOk:
    """Connect the database agent to an external PostgreSQL database."""
    success, message = await service.connect_external_db(
        user_key=user_key,
        host=req.host,
        port=req.port,
        database=req.database,
        username=req.username,
        password=req.password,
    )
    return DbConnectOk(success=success, message=message)


@router.get("/api/db/status", response_model=DbConnectOk)
async def db_status(
    user_key: str = Depends(get_user_key),
    service: ChatService = Depends(get_chat_service),
) -> DbConnectOk:
    """Check whether the database agent currently has an active connection."""
    connected, message = await service.check_db_connection(user_key=user_key)
    return DbConnectOk(success=connected, message=message)


@router.post("/api/db/disconnect", response_model=DbConnectOk)
async def db_disconnect(
    user_key: str = Depends(get_user_key),
    service: ChatService = Depends(get_chat_service),
) -> DbConnectOk:
    """Disconnect the database agent from its current external database."""
    success, message = await service.disconnect_external_db(user_key=user_key)
    return DbConnectOk(success=success, message=message)


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
