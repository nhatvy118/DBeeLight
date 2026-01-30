from __future__ import annotations

from fastapi import APIRouter, Depends

from internal.controllers.schemas import NewSessionRequest
from internal.dependencies import get_sessions_usecase, get_user_key
from internal.usecases.sessions_usecase import SessionsUseCase


router = APIRouter()

@router.get("/api/sessions")
async def list_sessions(
    project_id: str | None = None,
    unassigned_only: bool = False,
    user_key: str = Depends(get_user_key),
    usecase: SessionsUseCase = Depends(get_sessions_usecase),
):
    """
    List sessions for the current user.
    
    Query parameters:
    - project_id: Filter by specific project ID (e.g., ?project_id=123)
    - unassigned_only: If True, only return sessions where project_id IS NULL (e.g., ?unassigned_only=true)
    
    Examples:
    - GET /api/sessions?unassigned_only=true -> Get unassigned sessions (project_id IS NULL)
    - GET /api/sessions?project_id=123 -> Get sessions of project 123
    - GET /api/sessions -> Get all sessions
    """
    sessions = await usecase.list_sessions(user_key, project_id=project_id, unassigned_only=unassigned_only)
    return {"success": True, "sessions": sessions}

@router.post("/api/sessions/new")
async def create_session(
    req: NewSessionRequest,
    user_key: str = Depends(get_user_key),
    usecase: SessionsUseCase = Depends(get_sessions_usecase),
):
    session_id, session_info = await usecase.create_session(user_key, req.name, req.project_id)
    return {"success": True, "session_id": session_id, "session_info": session_info}

@router.get("/api/sessions/{session_id}")
async def get_session(
    session_id: str,
    user_key: str = Depends(get_user_key),
    usecase: SessionsUseCase = Depends(get_sessions_usecase),
):
    session_info, messages = await usecase.get_session(user_key, session_id)
    return {"success": True, "session_info": session_info, "messages": messages}

