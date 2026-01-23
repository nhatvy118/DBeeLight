from __future__ import annotations

import secrets

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from internal.repositories.google_oauth_repository import GoogleOAuthRepository


class AuthUseCase:
    def __init__(self, google_repo: GoogleOAuthRepository, frontend_url: str = "http://localhost:5173"):
        self._google_repo = google_repo
        self._frontend_url = frontend_url.rstrip("/")

    def google_login(self, request: Request, next_path: str) -> RedirectResponse:
        try:
            client_id, _client_secret = self._google_repo.require_client()
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

        state = secrets.token_urlsafe(16)
        request.session["google_oauth_state"] = state
        request.session["google_oauth_next"] = next_path or "/chat"

        redirect_uri = str(request.url_for("google_callback"))
        auth_url = self._google_repo.build_auth_url(client_id=client_id, redirect_uri=redirect_uri, state=state)
        return RedirectResponse(url=auth_url)

    def google_callback(self, request: Request, code: str | None, state: str | None) -> RedirectResponse:
        expected_state = request.session.get("google_oauth_state")
        if not expected_state or not state or state != expected_state:
            raise HTTPException(status_code=400, detail="Invalid OAuth state")
        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code")

        try:
            client_id, client_secret = self._google_repo.require_client()
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

        redirect_uri = str(request.url_for("google_callback"))
        token_resp = self._google_repo.exchange_code_for_token(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, code=code
        )
        id_token = token_resp.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise HTTPException(status_code=400, detail="Missing id_token in token response")
        access_token = token_resp.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status_code=400, detail="Missing access_token in token response")

        token_info = self._google_repo.token_info(id_token)
        if token_info.get("aud") != client_id:
            raise HTTPException(status_code=400, detail="Invalid token audience")

        # Fetch richer profile via OpenID userinfo endpoint
        try:
            userinfo = self._google_repo.user_info(access_token)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch Google userinfo: {str(e)}") from e

        # Merge: keep validated subject from tokeninfo, enrich from userinfo
        user = {
            "sub": token_info.get("sub") or userinfo.get("sub"),
            "email": userinfo.get("email") or token_info.get("email"),
            "email_verified": userinfo.get("email_verified") if "email_verified" in userinfo else token_info.get("email_verified"),
            "name": userinfo.get("name") or token_info.get("name"),
            "picture": userinfo.get("picture") or token_info.get("picture"),
            "given_name": userinfo.get("given_name"),
            "family_name": userinfo.get("family_name"),
            "locale": userinfo.get("locale"),
            # hosted domain (Google Workspace) might appear in tokeninfo and/or userinfo
            "hd": userinfo.get("hd") or token_info.get("hd"),
        }

        request.session.pop("google_oauth_state", None)
        next_path = request.session.pop("google_oauth_next", "/chat") or "/chat"
        request.session["user"] = user

        return RedirectResponse(url=f"{self._frontend_url}{next_path}")

    def me(self, request: Request) -> JSONResponse:
        user = request.session.get("user")
        if not user:
            return JSONResponse({"success": True, "authenticated": False, "user": None})
        return JSONResponse({"success": True, "authenticated": True, "user": user})

    def logout(self, request: Request) -> JSONResponse:
        request.session.pop("user", None)
        request.session.pop("google_oauth_state", None)
        request.session.pop("google_oauth_next", None)
        return JSONResponse({"success": True})

