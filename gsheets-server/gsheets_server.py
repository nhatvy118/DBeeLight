"""MCP server exposing Google Sheets / Drive read tools.

Per-user auth model
-------------------
The api-server stores each app user's Google OAuth tokens (access +
refresh, encrypted) in Postgres. When the agent for a user spawns this
MCP server, the parent injects the user's ``google_sub`` via the
``USER_GOOGLE_SUB`` env var. The server looks up that user's tokens in
the DB on every API call, refreshes the access_token if expired, and
calls the Google API on the user's behalf.

Required env vars
~~~~~~~~~~~~~~~~~
- ``USER_GOOGLE_SUB`` — Google identifier of the app user this server
  speaks for (passed by ``base_agent.connect_to_server``).
- ``DATABASE_URL`` (or ``DB_URL``) — Postgres connection string for
  ``users`` table lookups.
- ``GOOGLE_CLIENT_ID`` + ``GOOGLE_CLIENT_SECRET`` — needed to refresh
  tokens.
- ``TOKEN_ENCRYPTION_KEY`` — Fernet key matching api-server's, so we
  can decrypt the stored tokens. If absent, tokens are read as
  plaintext (dev only).

Tools
~~~~~
- ``get_spreadsheet_info(spreadsheet_id)`` — list sheet tabs + sizes.
- ``read_google_sheet(spreadsheet_id, range)`` — read cell values.

(Drive search is intentionally not exposed — see ``DEFAULT_SCOPES`` in
api-server's google_oauth_repository for why we don't request
``drive.readonly``. The user must paste a sheet URL/ID directly.)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Boot-time env validation. We log to stderr (stdout is reserved for the
# MCP transport's JSON-RPC frames).
# ---------------------------------------------------------------------------
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("gsheets-server")

USER_GOOGLE_SUB = (os.getenv("USER_GOOGLE_SUB") or "").strip()
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "").strip()
GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()

if not USER_GOOGLE_SUB:
    logger.warning(
        "USER_GOOGLE_SUB env not set — every tool call will fail with a "
        "clear error. The api-server should pass this when spawning."
    )

if not DATABASE_URL:
    logger.warning(
        "DATABASE_URL not set — tool calls will fail. The api-server "
        "should pass DATABASE_URL through the spawn env."
    )


# ---------------------------------------------------------------------------
# Token decryption — must match api-server's internal/utils/token_crypto.py
# ---------------------------------------------------------------------------
def _decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw_key = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    if not raw_key:
        return value  # dev fallback — caller already warned
    try:
        from cryptography.fernet import Fernet, InvalidToken

        f = Fernet(raw_key.encode("utf-8"))
        try:
            return f.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            # Pre-encryption value (stored before encryption was enabled)
            # or wrong key. Returning the raw value lets the plaintext path
            # keep working; a wrong key will surface as a Google API error
            # downstream instead of crashing here.
            return value
    except Exception as e:
        logger.error(
            "TOKEN_ENCRYPTION_KEY appears invalid (%s). Generate a proper "
            "key with: python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())' and set it in "
            "api-server/.env. Without a matching key, Google API calls "
            "will fail with auth errors.", e,
        )
        return value


def _encrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw_key = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    if not raw_key:
        return value
    try:
        from cryptography.fernet import Fernet

        f = Fernet(raw_key.encode("utf-8"))
        return f.encrypt(value.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.warning("Token encryption failed: %s — storing raw", e)
        return value


# ---------------------------------------------------------------------------
# DB pool (lazy, single per process)
# ---------------------------------------------------------------------------
_pool: Optional[asyncpg.Pool] = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not configured")
        _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=2)
    return _pool


# ---------------------------------------------------------------------------
# Token retrieval + refresh
# ---------------------------------------------------------------------------
def _refresh_token_via_http(refresh_token: str) -> dict[str, Any]:
    """Call Google's token endpoint to mint a new access_token. Stdlib HTTP
    so we don't need extra deps just for this."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set — cannot refresh"
        )
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=encoded, method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


async def _get_valid_access_token() -> str:
    """Fetch the user's tokens from DB, refresh if near/past expiry, return
    a usable ``access_token``. Raises if the user has no stored tokens."""
    if not USER_GOOGLE_SUB:
        raise RuntimeError(
            "Server has no USER_GOOGLE_SUB — request lacks user identity"
        )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT google_access_token, google_refresh_token,
                   google_token_expires_at, google_token_scope
            FROM users WHERE google_sub = $1
            """,
            USER_GOOGLE_SUB,
        )

    if row is None:
        raise RuntimeError(f"User {USER_GOOGLE_SUB} not found in DB")
    access_token = _decrypt(row["google_access_token"])
    refresh_token = _decrypt(row["google_refresh_token"])
    expires_at = row["google_token_expires_at"]

    if not access_token and not refresh_token:
        raise RuntimeError(
            "User has no Google tokens stored. Re-login with Google to "
            "grant Sheets/Drive access."
        )

    # Refresh if the access_token is missing or expires within 60 seconds.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    needs_refresh = (
        not access_token
        or (expires_at is not None and expires_at <= now + timedelta(seconds=60))
    )

    if needs_refresh:
        if not refresh_token:
            raise RuntimeError(
                "Access token expired and no refresh_token available. "
                "User must log in again to grant offline access."
            )
        logger.info("Refreshing Google access_token for user")
        token_resp = _refresh_token_via_http(refresh_token)
        new_access = token_resp.get("access_token")
        expires_in = int(token_resp.get("expires_in") or 3600)
        if not new_access:
            raise RuntimeError(f"Refresh failed: {token_resp}")
        new_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            seconds=expires_in
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET google_access_token = $2,
                    google_token_expires_at = $3
                WHERE google_sub = $1
                """,
                USER_GOOGLE_SUB,
                _encrypt(new_access),
                new_expires_at,
            )
        return new_access

    return access_token


async def _build_credentials() -> Credentials:
    """Build a google-auth Credentials object using the latest valid token."""
    access_token = await _get_valid_access_token()
    return Credentials(token=access_token)


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------
mcp = FastMCP("gsheets")


def _http_error_message(e: HttpError) -> str:
    try:
        details = e.error_details if hasattr(e, "error_details") else None
        if details:
            return f"Google API error: {details}"
    except Exception:
        pass
    return f"Google API error: {e}"


@mcp.tool()
async def get_spreadsheet_info(spreadsheet_id: str) -> dict:
    """Inspect a Google Spreadsheet's structure: sheet tabs and their
    dimensions. Use this before ``read_google_sheet`` to discover
    available sheets and pick a good range.

    Args:
        spreadsheet_id: The spreadsheet ID (the long string in a Google
            Sheets URL between ``/d/`` and ``/edit``).
    """
    if not spreadsheet_id:
        return {"error": "spreadsheet_id is required"}
    try:
        creds = await _build_credentials()
        sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        meta = sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            includeGridData=False,
        ).execute()
        out_sheets = []
        for s in meta.get("sheets", []):
            props = s.get("properties", {})
            grid = props.get("gridProperties", {}) or {}
            out_sheets.append({
                "sheet_id": props.get("sheetId"),
                "title": props.get("title"),
                "row_count": grid.get("rowCount"),
                "column_count": grid.get("columnCount"),
            })
        return {
            "spreadsheet_id": meta.get("spreadsheetId"),
            "title": (meta.get("properties") or {}).get("title"),
            "url": meta.get("spreadsheetUrl"),
            "sheets": out_sheets,
        }
    except HttpError as e:
        return {"error": _http_error_message(e)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def read_google_sheet(
    spreadsheet_id: str,
    range: str = "A1:Z1000",
) -> dict:
    """Read cell values from a Google Sheet.

    Args:
        spreadsheet_id: The spreadsheet ID.
        range: A1-style range, optionally prefixed with sheet name
            (e.g. ``"Sheet1!A1:D100"`` or just ``"A1:D100"`` for the
            first sheet).

    Returns: ``{"range": <resolved>, "values": [[row1...], [row2...], ...]}``.
    """
    if not spreadsheet_id:
        return {"error": "spreadsheet_id is required"}
    try:
        creds = await _build_credentials()
        sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range or "A1:Z1000",
            majorDimension="ROWS",
        ).execute()
        return {
            "range": resp.get("range"),
            "values": resp.get("values", []),
        }
    except HttpError as e:
        return {"error": _http_error_message(e)}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
