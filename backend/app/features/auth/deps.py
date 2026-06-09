from __future__ import annotations

from fastapi import HTTPException, Request, status


def get_current_user_id(request: Request) -> str:
    """Get google_sub from the cookie session (matches FE using credentials:'include')."""
    user = request.session.get("user") if hasattr(request, "session") else None
    sub = (user or {}).get("sub") if isinstance(user, dict) else None
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
    return str(sub)
