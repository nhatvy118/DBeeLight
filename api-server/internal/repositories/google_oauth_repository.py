from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Scopes requested at login. ``openid`` + ``email`` + ``profile`` are required
# for app identity; ``spreadsheets.readonly`` lets the gsheets MCP server read
# any sheet the user provides a URL/ID for.
#
# We deliberately AVOID ``drive.readonly`` — that's a *restricted* scope that
# triggers Google's CASA security audit before publishing. With only
# ``spreadsheets.readonly`` (sensitive, not restricted) we still need users
# to be in the OAuth test users list during development, but the verification
# path to "Production" is much lighter (no security audit).
#
# Trade-off: cannot list/search the user's Sheets via Drive — the user has
# to paste a Google Sheets URL or spreadsheet_id explicitly.
DEFAULT_SCOPES = (
    "openid email profile "
    "https://www.googleapis.com/auth/spreadsheets.readonly"
)


class GoogleOAuthRepository:
    """
    Repository layer that talks to Google OAuth2 endpoints.
    Uses stdlib urllib to avoid extra deps.
    """

    def require_client(self) -> tuple[str, str]:
        logger.info("Repository: Checking Google OAuth client configuration")
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            logger.error("Repository: Google OAuth credentials not configured")
            raise RuntimeError(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in api-server/.env"
            )
        logger.info("Repository: Google OAuth client configuration found")
        return client_id, client_secret

    def build_auth_url(self, client_id: str, redirect_uri: str, state: str) -> str:
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

    def refresh_access_token(
        self, client_id: str, client_secret: str, refresh_token: str
    ) -> dict[str, Any]:
        """Exchange a refresh_token for a fresh access_token.

        Response body shape (from Google): ``{access_token, expires_in,
        scope, token_type, id_token?}``. Note: ``refresh_token`` is usually
        NOT included — keep the existing one.
        """
        logger.info("Repository: Refreshing Google access_token")
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=encoded, method="POST"
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        return json.loads(body)

    def exchange_code_for_token(self, client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict[str, Any]:
        logger.info(f"Repository: Exchanging OAuth code for token, redirect_uri={redirect_uri}")
        try:
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
            token_data = json.loads(body)
            logger.info("Repository: Successfully exchanged code for token")
            return token_data
        except Exception as e:
            logger.error(f"Repository: Error exchanging code for token: {e}", exc_info=True)
            raise

    def token_info(self, id_token: str) -> dict[str, Any]:
        logger.info("Repository: Fetching token info from Google")
        try:
            url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
            info = json.loads(body)
            logger.info("Repository: Successfully fetched token info")
            return info
        except Exception as e:
            logger.error(f"Repository: Error fetching token info: {e}", exc_info=True)
            raise

    def user_info(self, access_token: str) -> dict[str, Any]:
        """
        Fetch OpenID Connect userinfo using access_token.
        Docs: https://openid.net/specs/openid-connect-core-1_0.html#UserInfo
        """
        logger.info("Repository: Fetching user info from Google")
        try:
            req = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo", method="GET")
            req.add_header("Authorization", f"Bearer {access_token}")
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
            info = json.loads(body)
            logger.info(f"Repository: Successfully fetched user info, sub={info.get('sub')}")
            return info
        except Exception as e:
            logger.error(f"Repository: Error fetching user info: {e}", exc_info=True)
            raise
