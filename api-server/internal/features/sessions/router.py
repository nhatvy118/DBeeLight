from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from internal.dependencies import get_user_key
from internal.features.file.dependencies import get_file_service
from internal.features.project.dependencies import get_project_repository
from internal.features.sessions.dependencies import get_sessions_service
from internal.features.share.dependencies import get_chat_share_repository
from internal.features.sessions.schema import NewSessionRequest
from internal.features.sessions.service import SessionsService
from internal.features.share.repository import ChatShareRepository
from internal.features.sessions.export_service import (
    filename_for_session,
    session_to_markdown,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    project_id: str | None = None,
    unassigned_only: bool = False,
    user_key: str = Depends(get_user_key),
    service: SessionsService = Depends(get_sessions_service),
):
    """
    List sessions for the current user.

    Query parameters:
    - project_id: Filter by specific project ID (e.g., ?project_id=123)
    - unassigned_only: If True, only return sessions where project_id IS NULL (e.g., ?unassigned_only=true)
    """
    sessions = await service.list_sessions(user_key, project_id=project_id, unassigned_only=unassigned_only)
    return {"success": True, "sessions": sessions}


@router.post("/new")
async def create_session(
    req: NewSessionRequest,
    user_key: str = Depends(get_user_key),
    service: SessionsService = Depends(get_sessions_service),
):
    session_id, session_info = await service.create_session(user_key, req.name, req.project_id)
    return {"success": True, "session_id": session_id, "session_info": session_info}


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    user_key: str = Depends(get_user_key),
    service: SessionsService = Depends(get_sessions_service),
):
    session_info, messages = await service.get_session(user_key, session_id)

    # If this session is a forked share, include permission info so the UI
    # can render a banner and gate the chat input.
    share_info = None
    pool = getattr(request.app.state, "db_pool", None)
    if pool is not None:
        share_repo: ChatShareRepository = get_chat_share_repository(request)
        info = await share_repo.get_share_permission_for_session(session_id)
        if info is not None:
            share_info = {
                "permission": info["permission"],
                "revoked": info["revoked"],
                "share_id": str(info["share_id"]),
            }

    return {
        "success": True,
        "session_info": session_info,
        "messages": messages,
        "share_info": share_info,
    }


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    user_key: str = Depends(get_user_key),
):
    """Delete session row, attached file rows, ``file_handle/...`` session tree, and temp SQLite DB."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    try:
        fsvc = get_file_service(request, get_project_repository(request))
        await fsvc.cleanup_session_files(session_id, user_key)
    except Exception as e:
        logger.warning("Session file cleanup: %s", e)
    deleted_id = await pool.fetchval(
        "DELETE FROM session WHERE id = $1 AND user_id = $2 RETURNING id",
        session_id,
        user_key,
    )
    if deleted_id is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True}


@router.get("/{session_id}/export.md")
async def export_session_markdown(
    session_id: str,
    request: Request,
    user_key: str = Depends(get_user_key),
    service: SessionsService = Depends(get_sessions_service),
):
    """Download the chat session as a Markdown file."""
    session_info, messages = await service.get_session(user_key, session_id)

    owner_name = None
    owner_email = None
    user = request.session.get("user") if hasattr(request, "session") else None
    if isinstance(user, dict):
        owner_name = user.get("name") if isinstance(user.get("name"), str) else None
        owner_email = user.get("email") if isinstance(user.get("email"), str) else None

    project_name = None
    pool = getattr(request.app.state, "db_pool", None)
    project_id = (session_info or {}).get("project_id") if isinstance(session_info, dict) else None
    if pool is not None and project_id:
        try:
            project_repo = get_project_repository(request)
            project = await project_repo.get_project_by_id(str(project_id), user_key)
            if project:
                project_name = project.get("name")
        except Exception:
            pass

    md = session_to_markdown(
        session_info=session_info,
        messages=messages,
        owner_name=owner_name,
        owner_email=owner_email,
        project_name=project_name,
    )
    filename = filename_for_session(session_info, ext="md")
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
