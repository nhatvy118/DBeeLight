from __future__ import annotations

from fastapi import APIRouter, Depends

from internal.controllers.schemas import NewSessionRequest
from internal.dependencies import get_sessions_usecase, get_user_key
from internal.usecases.sessions_usecase import SessionsUseCase


router = APIRouter()

@router.get("/api/sessions")
async def list_sessions(
    user_key: str = Depends(get_user_key),
    usecase: SessionsUseCase = Depends(get_sessions_usecase),
):
    sessions = await usecase.list_sessions(user_key)
    return {"success": True, "sessions": sessions}

@router.post("/api/sessions/new")
async def create_session(
    req: NewSessionRequest,
    user_key: str = Depends(get_user_key),
    usecase: SessionsUseCase = Depends(get_sessions_usecase),
):
    session_id, session_info = await usecase.create_session(user_key, req.name)
    return {"success": True, "session_id": session_id, "session_info": session_info}

@router.get("/api/sessions/{session_id}")
async def get_session(
    session_id: str,
    user_key: str = Depends(get_user_key),
    usecase: SessionsUseCase = Depends(get_sessions_usecase),
):
    session_info, messages = await usecase.get_session(user_key, session_id)
    return {"success": True, "session_info": session_info, "messages": messages}

