from __future__ import annotations

import logging
import os
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from internal.repositories.google_oauth_repository import GoogleOAuthRepository
from internal.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuthUseCase:
    def __init__(
        self,
        google_repo: GoogleOAuthRepository,
        user_repo: UserRepository | None,
        frontend_url: str = "http://localhost:5173",
    ):
        self._google_repo = google_repo
        self._user_repo = user_repo
        self._frontend_url = frontend_url.rstrip("/")

    def google_login(self, request: Request, next_path: str) -> RedirectResponse:
        logger.info(f"UseCase: Initiating Google login, next_path={next_path}")
        try:
            client_id, _client_secret = self._google_repo.require_client()
        except RuntimeError as e:
            logger.error(f"UseCase: Google OAuth not configured: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

        state = secrets.token_urlsafe(16)
        request.session["google_oauth_state"] = state
        request.session["google_oauth_next"] = next_path or "/chat"
        logger.info(f"UseCase: Created OAuth state, redirecting to Google")

        # Use explicit base URL so redirect_uri matches Google Console (fixes flowName=GeneralOAuthFlow / redirect_uri_mismatch)
        base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("API_BASE_URL") or "").strip().rstrip("/")
        if base:
            redirect_uri = f"{base}/api/auth/google/callback"
        else:
            redirect_uri = str(request.url_for("google_callback"))
        logger.info(f"UseCase: OAuth redirect_uri={redirect_uri} (add this exact URL in Google Cloud Console → Credentials → Authorized redirect URIs)")
        auth_url = self._google_repo.build_auth_url(client_id=client_id, redirect_uri=redirect_uri, state=state)
        return RedirectResponse(url=auth_url)

    async def google_callback(self, request: Request, code: str | None, state: str | None) -> RedirectResponse:
        logger.info(f"UseCase: Processing Google OAuth callback, code={'present' if code else 'missing'}, state={'present' if state else 'missing'}")
        expected_state = request.session.get("google_oauth_state")
        if not expected_state or not state or state != expected_state:
            logger.warning(f"UseCase: Invalid OAuth state. Expected: {expected_state}, Got: {state}")
            raise HTTPException(status_code=400, detail="Invalid OAuth state")
        if not code:
            logger.error("UseCase: Missing authorization code")
            raise HTTPException(status_code=400, detail="Missing authorization code")

        try:
            client_id, client_secret = self._google_repo.require_client()
        except RuntimeError as e:
            logger.error(f"UseCase: Google OAuth not configured: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

        base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("API_BASE_URL") or "").strip().rstrip("/")
        if base:
            redirect_uri = f"{base}/api/auth/google/callback"
        else:
            redirect_uri = str(request.url_for("google_callback"))
        logger.info(f"UseCase: Exchanging code for token, redirect_uri={redirect_uri}")
        try:
            token_resp = self._google_repo.exchange_code_for_token(
                client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, code=code
            )
        except Exception as e:
            logger.error(f"UseCase: Error exchanging code for token: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to exchange code for token: {str(e)}") from e
            
        id_token = token_resp.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            logger.error("UseCase: Missing id_token in token response")
            raise HTTPException(status_code=400, detail="Missing id_token in token response")
        access_token = token_resp.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            logger.error("UseCase: Missing access_token in token response")
            raise HTTPException(status_code=400, detail="Missing access_token in token response")

        logger.info("UseCase: Validating token info")
        try:
            token_info = self._google_repo.token_info(id_token)
        except Exception as e:
            logger.error(f"UseCase: Error fetching token info: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to validate token: {str(e)}") from e
            
        if token_info.get("aud") != client_id:
            logger.warning(f"UseCase: Invalid token audience. Expected: {client_id}, Got: {token_info.get('aud')}")
            raise HTTPException(status_code=400, detail="Invalid token audience")

        # Fetch richer profile via OpenID userinfo endpoint
        logger.info("UseCase: Fetching user info from Google")
        try:
            userinfo = self._google_repo.user_info(access_token)
        except Exception as e:
            logger.error(f"UseCase: Error fetching user info: {e}", exc_info=True)
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

        # Persist user into DB on every login (insert if new; update name if existing).
        if self._user_repo is None:
            raise HTTPException(
                status_code=500,
                detail="Database is not configured. Set DATABASE_URL (or DB_URL) and restart the server.",
            )

        google_sub = user.get("sub")
        if not isinstance(google_sub, str) or not google_sub.strip():
            raise HTTPException(status_code=400, detail="Missing Google subject (sub)")
        display_name = user.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = user.get("email") if isinstance(user.get("email"), str) else "Unknown"

        email_value = user.get("email") if isinstance(user.get("email"), str) else None

        logger.info(f"UseCase: Persisting user to database, google_sub={google_sub}, name={display_name}, email={email_value}")
        try:
            # Persist Google tokens too so MCP servers (gsheets-server) can
            # call Google APIs on behalf of this user. ``refresh_token`` is
            # only present on consent flow; subsequent logins without consent
            # omit it — UserRepository COALESCEs to keep the existing one.
            db_user = await self._user_repo.upsert_user(
                google_sub=google_sub,
                name=display_name,
                email=email_value,
                access_token=token_resp.get("access_token"),
                refresh_token=token_resp.get("refresh_token"),
                expires_in=int(token_resp.get("expires_in") or 0) or None,
                scope=token_resp.get("scope"),
            )
            user_id = db_user.get("id")
            request.session["user_id"] = user_id
            logger.info(f"UseCase: User persisted successfully, user_id={user_id}")
        except Exception as e:
            logger.error(f"UseCase: Error persisting user: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to persist user: {str(e)}") from e

        logger.info(f"UseCase: OAuth callback successful, redirecting to {next_path}")
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

