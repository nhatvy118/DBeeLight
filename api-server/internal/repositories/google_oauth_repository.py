from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


class GoogleOAuthRepository:
    """
    Repository layer that talks to Google OAuth2 endpoints.
    Uses stdlib urllib to avoid extra deps.
    """

    def require_client(self) -> tuple[str, str]:
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise RuntimeError(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in api-server/.env"
            )
        return client_id, client_secret

    def build_auth_url(self, client_id: str, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "include_granted_scopes": "true",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    def exchange_code_for_token(self, client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict[str, Any]:
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        return json.loads(body)

    def token_info(self, id_token: str) -> dict[str, Any]:
        url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        return json.loads(body)

    def user_info(self, access_token: str) -> dict[str, Any]:
        """
        Fetch OpenID Connect userinfo using access_token.
        Docs: https://openid.net/specs/openid-connect-core-1_0.html#UserInfo
        """
        req = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo", method="GET")
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        return json.loads(body)
