"""Auth service — Google OAuth redirect + cookie session (matches the old api-server).

User stored in request.session["user"] (sub/email/name...). current_user = session["user"]["sub"].
"""
from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import get_settings
from app.features.auth import repository as repo
from app.features.auth.google_oauth import GoogleOAuthRepository

logger = logging.getLogger("auth")
_google = GoogleOAuthRepository()


def _redirect_uri(request: Request) -> str:
    logger.info("→ _redirect_uri(request=%r)", request)  # autolog
    s = get_settings()
    base = (s.public_base_url or "").strip().rstrip("/")
    return f"{base}/api/auth/google/callback" if base else str(request.url_for("google_callback"))


def google_login(request: Request, next_path: str) -> RedirectResponse:
    logger.info("→ google_login(request=%r next_path=%r)", request, next_path)  # autolog
    client_id, _ = _google.require_client()
    state = secrets.token_urlsafe(16)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_next"] = next_path or "/chat"
    url = _google.build_auth_url(client_id, _redirect_uri(request), state)
    return RedirectResponse(url=url)


async def google_callback(request: Request, code: str | None, state: str | None) -> RedirectResponse:
    logger.info("→ google_callback(request=%r code=%r state=%r)", request, code, state)  # autolog
    s = get_settings()
    fe = s.frontend_url.rstrip("/")
    expected = request.session.get("google_oauth_state")
    if not expected or state != expected:
        if request.session.get("user"):
            return RedirectResponse(url=f"{fe}{request.session.get('google_oauth_next') or '/chat'}")
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    client_id, client_secret = _google.require_client()
    redirect_uri = _redirect_uri(request)
    token_resp = _google.exchange_code_for_token(client_id, client_secret, redirect_uri, code)
    id_token = token_resp.get("id_token")
    access_token = token_resp.get("access_token")
    if not id_token or not access_token:
        raise HTTPException(status_code=400, detail="Token response missing id_token/access_token")

    info = _google.token_info(id_token)
    if info.get("aud") != client_id:
        raise HTTPException(status_code=400, detail="Invalid token audience")
    userinfo = _google.user_info(access_token)

    user = {
        "sub": info.get("sub") or userinfo.get("sub"),
        "email": userinfo.get("email") or info.get("email"),
        "name": userinfo.get("name") or info.get("name"),
        "picture": userinfo.get("picture"),
    }
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="Missing Google subject (sub)")

    db_user = await repo.upsert_user(sub, user.get("email") or "", user.get("name") or "")
    request.session.pop("google_oauth_state", None)
    next_path = request.session.pop("google_oauth_next", "/chat") or "/chat"
    if db_user.get("disabled_at") is not None:
        request.session.clear()
        return RedirectResponse(url=f"{fe}/login?error=account_disabled")
    user["is_admin"] = bool(db_user.get("is_admin"))
    request.session["user"] = user
    return RedirectResponse(url=f"{fe}{next_path}")


def me(request: Request) -> JSONResponse:
    logger.info("→ me(request=%r)", request)  # autolog
    user = request.session.get("user")
    if not user:
        return JSONResponse({"success": True, "authenticated": False, "user": None})
    return JSONResponse({"success": True, "authenticated": True, "user": user})


def logout(request: Request) -> JSONResponse:
    logger.info("→ logout(request=%r)", request)  # autolog
    for k in ("user", "google_oauth_state", "google_oauth_next"):
        request.session.pop(k, None)
    return JSONResponse({"success": True})
