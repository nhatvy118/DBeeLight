"""Repository talking to Google OAuth2 (urllib, no extra deps)."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from app.config import get_settings

logger = logging.getLogger("auth.google")

DEFAULT_SCOPES = "openid email profile"


class GoogleOAuthRepository:
    def require_client(self) -> tuple[str, str]:
        logger.info("→ require_client()")  # autolog
        s = get_settings()
        cid = (s.google_client_id or "").strip()
        secret = (s.google_client_secret or "").strip()
        if not cid or not secret:
            raise RuntimeError(
                "Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env"
            )
        return cid, secret

    def build_auth_url(self, client_id: str, redirect_uri: str, state: str) -> str:
        logger.info("→ build_auth_url(client_id=%r redirect_uri=%r state=%r)", client_id, redirect_uri, state)  # autolog
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": DEFAULT_SCOPES,
            "include_granted_scopes": "true",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    def exchange_code_for_token(self, client_id, client_secret, redirect_uri, code) -> dict[str, Any]:
        logger.info("→ exchange_code_for_token(client_id=%r client_secret=*** redirect_uri=%r code=%r)", client_id, redirect_uri, code)  # autolog
        data = urllib.parse.urlencode({
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def token_info(self, id_token: str) -> dict[str, Any]:
        logger.info("→ token_info(id_token=***)")  # autolog
        url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def user_info(self, access_token: str) -> dict[str, Any]:
        logger.info("→ user_info(access_token=***)")  # autolog
        req = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo", method="GET")
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
