from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from internal.controllers.schemas import GenerateShareLinkRequest
from internal.dependencies import get_user_key

router = APIRouter()

# In-memory store for share tokens (in production, use database)
# Format: {share_token: {"session_id": str, "project_id": Optional[str], "user_key": str}}
_share_tokens: dict[str, dict[str, str | None]] = {}


@router.post("/api/share/generate")
async def generate_share_link(
    req: GenerateShareLinkRequest,
    request: Request,
    user_key: str = Depends(get_user_key),
):
    """
    Generate a shareable link for a session or project.
    Returns a share token that can be used to access the shared resource.
    """
    session_id = req.session_id
    project_id = req.project_id
    
    # Require at least one of session_id or project_id
    if not session_id and not project_id:
        raise HTTPException(status_code=400, detail="Please select a chat or project to share")

    # Generate unique share token
    share_token = secrets.token_urlsafe(16)

    # Store share token info
    _share_tokens[share_token] = {
        "session_id": session_id,
        "project_id": project_id,
        "user_key": user_key,
    }

    # Generate share URL
    frontend_url = request.headers.get("origin") or "http://localhost:5173"
    if session_id and project_id:
        share_url = f"{frontend_url}/chat/{project_id}/{session_id}?share={share_token}"
    elif project_id:
        share_url = f"{frontend_url}/chat/{project_id}?share={share_token}"
    elif session_id:
        share_url = f"{frontend_url}/chat/{session_id}?share={share_token}"
    else:
        share_url = f"{frontend_url}/chat?share={share_token}"

    return JSONResponse(
        content={
            "success": True,
            "share_token": share_token,
            "share_url": share_url,
        }
    )


@router.get("/api/share/{share_token}")
async def get_share_info(share_token: str):
    """Get information about a share token."""
    if share_token not in _share_tokens:
        raise HTTPException(status_code=404, detail="Share token not found")

    info = _share_tokens[share_token]
    return JSONResponse(
        content={
            "success": True,
            "session_id": info.get("session_id"),
            "project_id": info.get("project_id"),
        }
    )
