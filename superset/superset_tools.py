"""
Superset MCP Tools - FastMCP server for Apache Superset visualization.

Provides tools for authenticating with Superset, managing database connections,
executing SQL queries, creating virtual datasets, and building charts.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load env vars
load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
SUPERSET_URL = os.getenv("SUPERSET_URL", "http://localhost:8088").rstrip("/")
SUPERSET_USERNAME = os.getenv("SUPERSET_USERNAME", "admin")
SUPERSET_PASSWORD = os.getenv("SUPERSET_PASSWORD", "admin")
TOKEN_FILE = Path.home() / ".superset_mcp_token.json"
SUPERSET_HTTP_TIMEOUT = float(os.getenv("SUPERSET_HTTP_TIMEOUT", "120"))

# Naming policy: every project's DB in Superset is named with the project UUID
# directly (no prefix). This is the single source of truth for tool-level scoping.
# Empty prefix → DB name == project_id verbatim.
PROJECT_DB_NAME_PREFIX = ""

# When project_id is not passed (legacy / non-project chats), tools fall back to
# unscoped behavior. Set SUPERSET_REQUIRE_PROJECT_ID=1 in production to reject
# any tool call without a project_id.
REQUIRE_PROJECT_ID = os.getenv("SUPERSET_REQUIRE_PROJECT_ID", "0") == "1"

# Origins (parent windows) allowed to embed wrapper dashboards. Superset rejects
# the postMessage handshake if the parent origin isn't here and shows
# "This page is intended to be embedded in an iframe". Comma-separated env.
EMBED_ALLOWED_DOMAINS = [
    d.strip()
    for d in os.getenv(
        "SUPERSET_EMBED_ALLOWED_DOMAINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
    ).split(",")
    if d.strip()
]


# HTTP client (sync httpx.Client, shared for connection reuse)
_http_client: Optional[httpx.Client] = None
_csrf_token: Optional[str] = None


def _get_client() -> httpx.Client:
    """Get or create shared HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=SUPERSET_HTTP_TIMEOUT)
    return _http_client


def _load_token() -> Optional[dict]:
    """Load stored token from file."""
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except Exception:
        return None


def _save_token(token_data: dict) -> None:
    """Save token to file."""
    TOKEN_FILE.write_text(json.dumps(token_data))


def _is_token_valid(token_data: dict) -> bool:
    """Check if token is still valid."""
    import time
    expires_at = token_data.get("access_token_expires_at")
    if expires_at is None:
        return True  # No expiry info, assume valid
    return time.time() < (expires_at - 60)  # 60s buffer


def _get_access_token() -> str:
    """Get valid access token, refreshing if needed."""
    token_data = _load_token()
    if token_data and _is_token_valid(token_data):
        return token_data["access_token"]

    # Need to login
    return _login()


def _login() -> str:
    """Login to Superset and store token."""
    client = _get_client()

    global _csrf_token

    # First get CSRF token
    try:
        resp = client.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
        if resp.status_code == 200:
            _csrf_token = _extract_csrf_token(resp)
    except Exception:
        pass

    # Login
    login_data = {
        "username": SUPERSET_USERNAME,
        "password": SUPERSET_PASSWORD,
        "provider": "db",
        "refresh": True,
    }
    headers = {"Content-Type": "application/json"}
    if _csrf_token:
        headers["X-CSRFToken"] = _csrf_token

    resp = client.post(
        f"{SUPERSET_URL}/api/v1/security/login",
        json=login_data,
        headers=headers,
    )

    if resp.status_code != 200:
        raise Exception(f"Superset login failed: {resp.status_code} - {resp.text}")

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    # Parse expiry
    import time
    expires_in = data.get("expires_in", 900)  # default 15 min
    access_token_expires_at = time.time() + expires_in

    # Refresh token usually 30 days
    refresh_expires_in = data.get("refresh_token_expires_in", 2592000)

    token_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "access_token_expires_at": access_token_expires_at,
        "refresh_token_expires_at": time.time() + refresh_expires_in,
    }
    _save_token(token_data)

    # Update CSRF from response headers
    csrf = resp.headers.get("X-CSRFToken")
    if csrf:
        _csrf_token = csrf

    return access_token


def _refresh_token() -> str:
    """Refresh the access token using refresh token."""
    global _csrf_token

    token_data = _load_token()
    if not token_data or not token_data.get("refresh_token"):
        return _login()

    client = _get_client()

    # Get CSRF for refresh
    try:
        resp = client.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
        if resp.status_code == 200:
            _csrf_token = _extract_csrf_token(resp)
    except Exception:
        pass

    headers = {"Content-Type": "application/json"}
    if _csrf_token:
        headers["X-CSRFToken"] = _csrf_token

    resp = client.post(
        f"{SUPERSET_URL}/api/v1/security/refresh",
        headers={"Authorization": f"Bearer {token_data['refresh_token']}"},
    )

    if resp.status_code != 200:
        # Refresh failed, re-login
        return _login()

    data = resp.json()
    access_token = data.get("access_token")

    import time
    expires_in = data.get("expires_in", 900)
    token_data["access_token"] = access_token
    token_data["access_token_expires_at"] = time.time() + expires_in
    _save_token(token_data)

    return access_token


def _make_request(
    method: str,
    endpoint: str,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    """Make authenticated request to Superset API with auto-refresh."""
    access_token = _get_access_token()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    if _csrf_token:
        headers["X-CSRFToken"] = _csrf_token

    client = _get_client()
    url = f"{SUPERSET_URL}{endpoint}"

    if method.lower() == "get":
        resp = client.get(url, headers=headers, params=params)
    elif method.lower() == "post":
        resp = client.post(url, headers=headers, json=data)
    elif method.lower() == "put":
        resp = client.put(url, headers=headers, json=data)
    elif method.lower() == "delete":
        resp = client.delete(url, headers=headers)
    else:
        raise ValueError(f"Unsupported method: {method}")

    # Handle 401 - try refresh once
    if resp.status_code == 401:
        logger.info("Got 401, refreshing token...")
        access_token = _refresh_token()
        headers["Authorization"] = f"Bearer {access_token}"
        if method.lower() == "get":
            resp = client.get(url, headers=headers, params=params)
        elif method.lower() == "post":
            resp = client.post(url, headers=headers, json=data)
        elif method.lower() == "put":
            resp = client.put(url, headers=headers, json=data)
        elif method.lower() == "delete":
            resp = client.delete(url, headers=headers)

    if resp.status_code >= 400:
        logger.warning(f"[Superset] API error {resp.status_code}: {resp.text}")
        # Return error dict instead of raising — tools handle it gracefully
        return {
            "__error__": True,
            "status_code": resp.status_code,
            "message": f"Superset API error {resp.status_code}",
            "details": resp.text,
        }

    return resp.json() if resp.text else {}


def _extract_csrf_token(resp: httpx.Response) -> Optional[str]:
    """Safely extract CSRF token from Superset CSRF response.

    Handles variable response formats across Superset versions:
    - Superset ≥3.0: {"result": {"csrf_token": "..."}}
    - Superset <3.0: {"csrf_token": "..."}
    - Header-only: X-CSRFToken
    - Edge case: response is not a valid JSON dict
    """
    header_token = resp.headers.get("X-CSRFToken")
    try:
        raw = resp.json()
        if not isinstance(raw, dict):
            return header_token
        result = raw.get("result")
        # Superset ≥4.0: result is a plain JWT string (e.g. "IjI4..."), not a dict
        if isinstance(result, dict):
            token = result.get("csrf_token")
            if token:
                return token
        elif isinstance(result, str) and result:
            # Superset 4.x: result is the CSRF token directly as a JWT string
            return result
        token = raw.get("csrf_token")
        if token:
            return token
        return header_token
    except Exception:
        return header_token


def _ensure_csrf() -> None:
    """Ensure CSRF token is available for POST requests."""
    global _csrf_token
    if not _csrf_token:
        try:
            resp = _get_client().get(
                f"{SUPERSET_URL}/api/v1/security/csrf_token/",
                headers={"Authorization": f"Bearer {_get_access_token()}"},
            )
            if resp.status_code == 200:
                _csrf_token = _extract_csrf_token(resp)
        except Exception as e:
            logger.warning(f"Failed to get CSRF token: {e}")


# ==================== Project scoping (Phase 2) ====================
# In-memory cache: db_id → (project_id, expires_at). Avoids hitting Superset
# /api/v1/database/{id} on every tool call.
_DB_PROJECT_CACHE: dict[int, tuple[Optional[str], float]] = {}
_DB_PROJECT_CACHE_TTL = 60.0  # seconds


def _expected_db_name(project_id: str) -> str:
    return f"{PROJECT_DB_NAME_PREFIX}{project_id}"


def _project_id_for_db(database_id: int) -> Optional[str]:
    """Return the project_id that owns ``database_id``, or None if unscoped/unknown.

    Result derived from the Superset DB record's ``database_name``, which under
    current naming policy IS the project_id (UUID). Cached for ``_DB_PROJECT_CACHE_TTL`` seconds.
    """
    now = time.time()
    cached = _DB_PROJECT_CACHE.get(database_id)
    if cached and cached[1] > now:
        return cached[0]

    result = _make_request("get", f"/api/v1/database/{database_id}")
    if result.get("__error__"):
        # On error, don't cache — let next call retry
        return None
    record = result.get("result") or result
    name = ""
    if isinstance(record, dict):
        name = str(record.get("database_name") or "")
    pid: Optional[str] = None
    if name.startswith(PROJECT_DB_NAME_PREFIX):
        pid = name[len(PROJECT_DB_NAME_PREFIX):]
    _DB_PROJECT_CACHE[database_id] = (pid, now + _DB_PROJECT_CACHE_TTL)
    return pid


def _check_db_scope(database_id: int, project_id: Optional[str]) -> Optional[dict]:
    """Validate ``database_id`` belongs to ``project_id``.

    Returns None if access is allowed. Returns an error dict (suitable to be
    serialized as the tool result) if access is denied.

    Policy:
    - If project_id is None and REQUIRE_PROJECT_ID is set, deny.
    - If project_id is None and REQUIRE_PROJECT_ID is unset (legacy), allow.
    - If project_id is set, the DB's name MUST equal ``project_id``.
    """
    if not project_id:
        if REQUIRE_PROJECT_ID:
            return {
                "error": "project_id required",
                "message": "Tool call missing project_id; SUPERSET_REQUIRE_PROJECT_ID is enforced.",
            }
        return None  # legacy mode

    owner = _project_id_for_db(database_id)
    if owner is None:
        return {
            "error": "forbidden",
            "message": (
                f"Database {database_id} could not be resolved to a project; "
                f"refusing access from project {project_id}."
            ),
        }
    if owner != project_id:
        return {
            "error": "forbidden",
            "message": (
                f"Database {database_id} belongs to project {owner}, not {project_id}."
            ),
        }
    return None


def _scope_violation(message: str) -> str:
    return json.dumps({"error": "forbidden", "message": message}, indent=2)


def _invalidate_db_project_cache(database_id: Optional[int] = None) -> None:
    if database_id is None:
        _DB_PROJECT_CACHE.clear()
    else:
        _DB_PROJECT_CACHE.pop(database_id, None)


# Role that Guest Tokens assume — must match SUPERSET_GUEST_ROLE_NAME in
# superset_config.py. We grant ``all_database_access`` (one-time bootstrap) plus
# per-DB ``database_access`` (idempotent on every register) so chart queries
# don't 403 once a guest token mounts the iframe.
GUEST_ROLE_NAME = os.getenv("SUPERSET_GUEST_ROLE_NAME", "Gamma")
_BOOTSTRAP_DONE = False


def _bootstrap_guest_role_perms() -> None:
    """One-time bootstrap: grant ``all_database_access`` to the guest role.

    Without this, every newly-registered project DB needs its own per-PVM grant —
    and finding the PVM after registration is racy across Superset versions.
    Granting ``all_database_access`` once means any DB the guest's dashboard
    references is queryable. Cross-project isolation is enforced at:
    1. The MCP tool layer (Phase 2) — user A cannot create chart on project B's DB
    2. The guest token's ``resources`` field — token only valid for the specific
       embedded dashboard, can't navigate elsewhere

    Idempotent: skips if already granted. Best-effort: never raises.
    """
    global _BOOTSTRAP_DONE
    if _BOOTSTRAP_DONE:
        return
    try:
        # Find role
        roles = _make_request("get", "/api/v1/security/roles/", params={"page_size": 100})
        if roles.get("__error__"):
            logger.warning(f"[Superset] Bootstrap: GET /roles/ failed: {roles.get('message')}")
            return
        role_id: Optional[int] = None
        for r in (roles.get("result") or []):
            if isinstance(r, dict) and (r.get("name") or "").strip() == GUEST_ROLE_NAME:
                role_id = r.get("id")
                break
        if role_id is None:
            logger.warning(f"[Superset] Bootstrap: role '{GUEST_ROLE_NAME}' not found")
            return

        # Find PVM (all_database_access, all_database_access)
        target_pvm_id: Optional[int] = None
        page = 0
        while page <= 50:
            pvms = _make_request(
                "get", "/api/v1/security/permissions-resources/",
                params={"page": page, "page_size": 100},
            )
            if pvms.get("__error__"):
                logger.warning(f"[Superset] Bootstrap: GET /permissions-resources/ failed: {pvms.get('message')}")
                return
            results = pvms.get("result") or []
            if not results:
                break
            for pv in results:
                if not isinstance(pv, dict):
                    continue
                perm = pv.get("permission")
                view = pv.get("view_menu")
                pname = perm.get("name") if isinstance(perm, dict) else perm
                vname = view.get("name") if isinstance(view, dict) else view
                if pname == "all_database_access" and vname == "all_database_access":
                    target_pvm_id = pv.get("id")
                    break
            if target_pvm_id is not None or len(results) < 100:
                break
            page += 1
        if target_pvm_id is None:
            logger.warning(
                "[Superset] Bootstrap: PVM (all_database_access, all_database_access) not found. "
                "Falling back to per-DB grants."
            )
            return

        # Append to role if missing
        role_detail = _make_request("get", f"/api/v1/security/roles/{role_id}")
        if role_detail.get("__error__"):
            logger.warning(f"[Superset] Bootstrap: GET role/{role_id} failed: {role_detail.get('message')}")
            return
        rec = role_detail.get("result") or role_detail
        existing: list[int] = []
        if isinstance(rec, dict):
            for p in (rec.get("permissions") or []):
                if isinstance(p, dict) and isinstance(p.get("id"), int):
                    existing.append(p["id"])
                elif isinstance(p, int):
                    existing.append(p)
        if target_pvm_id in existing:
            logger.info(
                f"[Superset] Bootstrap: '{GUEST_ROLE_NAME}' already has all_database_access — skip"
            )
            _BOOTSTRAP_DONE = True
            return

        _ensure_csrf()
        put_resp = _make_request(
            "put",
            f"/api/v1/security/roles/{role_id}",
            data={"name": GUEST_ROLE_NAME, "permissions": existing + [target_pvm_id]},
        )
        if put_resp.get("__error__"):
            logger.warning(
                f"[Superset] Bootstrap: PUT role/{role_id} failed: {put_resp.get('message')}"
            )
            return
        _BOOTSTRAP_DONE = True
        logger.info(
            f"[Superset] Bootstrap: granted all_database_access to '{GUEST_ROLE_NAME}'"
        )
    except Exception as e:
        logger.warning(f"[Superset] _bootstrap_guest_role_perms error: {e}")


def _grant_database_to_guest_role(database_id: int, database_name: str) -> None:
    """Grant ``database_access`` on the new DB to the embed-view role.

    Superset stores per-database permissions as
    ``database_access on [<database_name>].(id:<id>)``. Without this grant,
    a Gamma-bound guest token can read the dashboard wrapper but Superset
    rejects the underlying chart query with 403.

    Strategy: fetch role list & PVM list without server-side filters (Rison
    operators on relationship fields are inconsistent across Superset versions)
    and match in Python. INFO-level logging on every step so the path is
    diagnosable from MCP logs. Best-effort: never raise.
    """
    perm_view_name = f"[{database_name}].(id:{database_id})"
    logger.info(
        f"[Superset] Grant: looking for PVM (database_access, '{perm_view_name}') "
        f"to add to role '{GUEST_ROLE_NAME}'"
    )

    try:
        # 1) Find role by listing all roles (small set, no pagination needed)
        roles = _make_request("get", "/api/v1/security/roles/", params={"page_size": 100})
        if roles.get("__error__"):
            logger.warning(f"[Superset] Grant: GET /roles/ failed: {roles.get('message')} — {roles.get('details')}")
            return
        role_list = roles.get("result") or []
        role_id: Optional[int] = None
        for r in role_list:
            if isinstance(r, dict) and (r.get("name") or "").strip() == GUEST_ROLE_NAME:
                role_id = r.get("id")
                break
        if role_id is None:
            available = [r.get("name") for r in role_list if isinstance(r, dict)]
            logger.warning(
                f"[Superset] Grant: role '{GUEST_ROLE_NAME}' not found among {available}"
            )
            return
        logger.info(f"[Superset] Grant: role '{GUEST_ROLE_NAME}' id={role_id}")

        # 2) Find PVM by paginating /permissions-resources/. Superset has hundreds
        # of PVMs; we walk pages until we find ours or exhaust.
        pvm_id: Optional[int] = None
        page = 0
        page_size = 100
        while True:
            pvms = _make_request(
                "get",
                "/api/v1/security/permissions-resources/",
                params={"page": page, "page_size": page_size},
            )
            if pvms.get("__error__"):
                logger.warning(
                    f"[Superset] Grant: GET /permissions-resources/ page={page} failed: "
                    f"{pvms.get('message')} — {pvms.get('details')}"
                )
                return
            pvm_list = pvms.get("result") or []
            if not pvm_list:
                break
            for pv in pvm_list:
                if not isinstance(pv, dict):
                    continue
                perm = pv.get("permission")
                view = pv.get("view_menu")
                perm_name = perm.get("name") if isinstance(perm, dict) else perm
                view_name = view.get("name") if isinstance(view, dict) else view
                if perm_name == "database_access" and view_name == perm_view_name:
                    pvm_id = pv.get("id")
                    break
            if pvm_id is not None:
                break
            if len(pvm_list) < page_size:
                break  # last page
            page += 1
            if page > 50:  # 5000 PVMs cap, safety
                break

        if pvm_id is None:
            logger.warning(
                f"[Superset] Grant: PVM (database_access, '{perm_view_name}') not found "
                f"after scanning {(page+1) * page_size} entries. "
                f"Superset may not have created it yet — try registering DB again."
            )
            return
        logger.info(f"[Superset] Grant: PVM id={pvm_id}")

        # 3) GET role's current permissions, append new one, PUT
        role_detail = _make_request("get", f"/api/v1/security/roles/{role_id}")
        if role_detail.get("__error__"):
            logger.warning(f"[Superset] Grant: GET role/{role_id} failed: {role_detail.get('message')}")
            return
        rec = role_detail.get("result") or role_detail
        existing_perms: list[int] = []
        if isinstance(rec, dict):
            for p in (rec.get("permissions") or []):
                if isinstance(p, dict) and isinstance(p.get("id"), int):
                    existing_perms.append(p["id"])
                elif isinstance(p, int):
                    existing_perms.append(p)
        if pvm_id in existing_perms:
            logger.info(f"[Superset] Grant: PVM {pvm_id} already granted to '{GUEST_ROLE_NAME}'")
            return
        new_perms = existing_perms + [pvm_id]

        _ensure_csrf()
        put_resp = _make_request(
            "put",
            f"/api/v1/security/roles/{role_id}",
            data={"name": GUEST_ROLE_NAME, "permissions": new_perms},
        )
        if put_resp.get("__error__"):
            logger.warning(
                f"[Superset] Grant: PUT role/{role_id} failed: "
                f"{put_resp.get('message')} — {put_resp.get('details')}"
            )
            return
        logger.info(
            f"[Superset] Grant: SUCCESS — added database_access on '{database_name}' "
            f"(PVM {pvm_id}) to role '{GUEST_ROLE_NAME}' (now {len(new_perms)} perms)"
        )
    except Exception as e:
        logger.warning(f"[Superset] _grant_database_to_guest_role error: {e}", exc_info=True)


# dataset_id (datasource_id for charts) → database_id, with TTL cache
_DATASET_DB_CACHE: dict[int, tuple[Optional[int], float]] = {}
_DATASET_DB_CACHE_TTL = 60.0


def _database_id_for_dataset(dataset_id: int) -> Optional[int]:
    now = time.time()
    cached = _DATASET_DB_CACHE.get(dataset_id)
    if cached and cached[1] > now:
        return cached[0]
    result = _make_request("get", f"/api/v1/dataset/{dataset_id}")
    if result.get("__error__"):
        return None
    record = result.get("result") or result
    db_id: Optional[int] = None
    if isinstance(record, dict):
        # Superset returns either {database: {id: X}} or {database_id: X}
        db = record.get("database")
        if isinstance(db, dict):
            db_id = db.get("id")
        if db_id is None:
            db_id = record.get("database_id")
    db_id_int = int(db_id) if db_id is not None else None
    _DATASET_DB_CACHE[dataset_id] = (db_id_int, now + _DATASET_DB_CACHE_TTL)
    return db_id_int


def _check_dataset_scope(dataset_id: int, project_id: Optional[str]) -> Optional[dict]:
    """Validate that ``dataset_id``'s underlying database belongs to ``project_id``."""
    if not project_id:
        if REQUIRE_PROJECT_ID:
            return {"error": "project_id required", "message": "Tool call missing project_id"}
        return None
    db_id = _database_id_for_dataset(dataset_id)
    if db_id is None:
        return {
            "error": "forbidden",
            "message": f"Dataset {dataset_id} could not be resolved to a database; refusing.",
        }
    return _check_db_scope(db_id, project_id)


def _chart_dataset_id(chart_id: int) -> Optional[int]:
    """Look up the datasource_id of a chart."""
    result = _make_request("get", f"/api/v1/chart/{chart_id}")
    if result.get("__error__"):
        return None
    record = result.get("result") or result
    if isinstance(record, dict):
        ds = record.get("datasource_id")
        if ds is not None:
            try:
                return int(ds)
            except (TypeError, ValueError):
                return None
    return None


def _check_chart_scope(chart_id: int, project_id: Optional[str]) -> Optional[dict]:
    if not project_id:
        if REQUIRE_PROJECT_ID:
            return {"error": "project_id required", "message": "Tool call missing project_id"}
        return None
    ds_id = _chart_dataset_id(chart_id)
    if ds_id is None:
        return {
            "error": "forbidden",
            "message": f"Chart {chart_id} could not be resolved to a dataset; refusing.",
        }
    return _check_dataset_scope(ds_id, project_id)


# ==================== FastMCP Server ====================

mcp = FastMCP("superset")


@mcp.tool()
def superset_authenticate(username: str, password: str) -> str:
    """
    Authenticate with Superset and store credentials.

    Args:
        username: Superset username
        password: Superset password

    Returns:
        Success message
    """
    global SUPERSET_USERNAME, SUPERSET_PASSWORD
    SUPERSET_USERNAME = username
    SUPERSET_PASSWORD = password

    # Clear old token to force re-login with new credentials
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

    _login()
    return f"Authenticated with Superset as {username}"


@mcp.tool()
def list_superset_databases(project_id: Optional[str] = None) -> str:
    """
    List databases registered in Superset, scoped to the caller's project.

    Args:
        project_id: When set, results are filtered to the single DB whose name
            equals ``project_id``. Without it, all DBs are returned (legacy mode).

    Returns:
        JSON list of databases with id, name, backend
    """
    if not project_id and REQUIRE_PROJECT_ID:
        return _scope_violation("project_id required to list Superset databases")

    result = _make_request("get", "/api/v1/database/", params={"page_size": 100})

    if result.get("__error__"):
        return json.dumps({
            "error": "Failed to list databases",
            "message": result.get("message", result.get("details", "Unknown error")),
        })

    databases = result.get("result", [])
    if not databases:
        databases = result.get("ids", [])  # fallback
    if not isinstance(databases, list):
        databases = []

    # Filter to project scope. We never let cross-project DBs leak in the listing —
    # the model could otherwise pick a foreign db_id and try to use it.
    if project_id:
        expected = _expected_db_name(project_id)
        databases = [
            db for db in databases
            if isinstance(db, dict) and str(db.get("database_name") or "") == expected
        ]

    return json.dumps(databases, indent=2)


@mcp.tool()
def register_database(
    name: str,
    sqlalchemy_uri: str,
    password: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """
    Register a new database connection in Superset, or return existing if name matches.

    Args:
        name: Display name for the database. When ``project_id`` is provided, ``name``
            MUST equal ``project_id`` — caller cannot register a DB under
            an arbitrary name to bypass scoping.
        sqlalchemy_uri: SQLAlchemy connection URI
        password: Optional database password (for masking in URI)
        project_id: Project UUID this DB belongs to. Required in scoped mode.

    Returns:
        JSON with database id and status
    """
    if not project_id and REQUIRE_PROJECT_ID:
        return _scope_violation("project_id required to register database")

    if project_id:
        expected = _expected_db_name(project_id)
        if name != expected:
            return _scope_violation(
                f"Refusing to register DB as '{name}' — project {project_id} requires name '{expected}'"
            )

    # Check if database with this name already exists TRƯỚC.
    # page_size=100 — Superset default is 25, which misses DBs on later pages
    # and makes the "already exists" retry below return a false negative.
    all_dbs = _make_request("get", "/api/v1/database/", params={"page_size": 100})

    if all_dbs.get("__error__"):
        return json.dumps({
            "status": "error",
            "message": f"Failed to list databases: {all_dbs.get('message', 'Unknown')}",
        })

    existing = all_dbs.get("result", [])
    if not isinstance(existing, list):
        existing = []

    # Tìm DB theo tên, reuse luôn nếu có
    def _find_existing(db_list):
        for db in db_list:
            if db.get("database_name", "").lower() == name.lower():
                # Idempotent grant on every reuse — repairs DBs registered
                # before the guest-role grant feature was added.
                try:
                    _bootstrap_guest_role_perms()
                    _grant_database_to_guest_role(int(db["id"]), db["database_name"])
                except Exception:
                    pass
                return json.dumps({
                    "id": db["id"],
                    "database_name": db["database_name"],
                    "status": "already_exists",
                    "message": f"Database '{name}' already registered with id {db['id']}",
                })
        return None

    found = _find_existing(existing)
    if found:
        return found

    # Mask password
    masked_uri = sqlalchemy_uri
    if password:
        masked_uri = sqlalchemy_uri.replace(password, "*****")

    payload = {
        "database_name": name,
        "sqlalchemy_uri": sqlalchemy_uri,
        "configuration_method": "sqlalchemy_form",
        "expose_in_sqllab": True,
    }

    _ensure_csrf()
    result = _make_request("post", "/api/v1/database/", data=payload)

    if result.get("__error__"):
        status_code = result.get("status_code", 0)
        details = result.get("details", "")
        combined = (details + str(result.get("message", ""))).lower()

        # 422 hoặc "already exists" → fetch lại list và reuse
        if status_code == 422 or "already exists" in combined:
            logger.info(f"[Superset] '{name}' already exists (race), re-fetching...")
            retry = _make_request("get", "/api/v1/database/", params={"page_size": 100})
            if not retry.get("__error__"):
                found = _find_existing(retry.get("result", []))
                if found:
                    return found

        return json.dumps({
            "status": "error",
            "message": f"Failed to register database '{name}': Superset API error {status_code}: {details}",
            "sqlalchemy_uri": masked_uri,
        })

    db_id = result.get("id") or result.get("result", {}).get("id")

    # Prime the scope cache so the very next tool call sees the new mapping
    # without waiting for a stale 60s lookup.
    if isinstance(db_id, int) and project_id:
        _DB_PROJECT_CACHE[db_id] = (project_id, time.time() + _DB_PROJECT_CACHE_TTL)

    # First-time setup: ensure guest role has ``all_database_access`` so Gamma
    # can query ANY project DB without per-DB grants. Idempotent skip after first.
    _bootstrap_guest_role_perms()

    # Belt-and-suspenders: explicit per-DB grant in case the all_database_access
    # bootstrap fell through (e.g., PVM not yet created on a fresh Superset).
    if isinstance(db_id, int):
        _grant_database_to_guest_role(db_id, name)

    return json.dumps({
        "id": db_id,
        "database_name": name,
        "status": "created",
        "message": f"Database '{name}' registered successfully",
        "sqlalchemy_uri": masked_uri,
    })


@mcp.tool()
def get_database_tables(
    database_id: int,
    schema: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """
    Get all tables in a Superset database.

    Args:
        database_id: Superset database ID
        schema: Optional schema name
        project_id: Project UUID — must own ``database_id`` in scoped mode

    Returns:
        JSON list of table names
    """
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    # Rison q: omit entirely when no schema (SQLite has no schema concept).
    # "(schema_name:)" with an empty value is invalid Rison and Superset rejects it with 400.
    params = {"q": f"(schema_name:{schema})"} if schema else {}
    result = _make_request("get", f"/api/v1/database/{database_id}/tables/", params=params)
    tables = result.get("result", [])
    return json.dumps(tables, indent=2)


@mcp.tool()
def get_table_metadata(
    database_id: int,
    table_name: str,
    schema: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """
    Get column metadata for a table.

    Args:
        database_id: Superset database ID
        table_name: Table name
        schema: Optional schema name
        project_id: Project UUID — must own ``database_id`` in scoped mode

    Returns:
        JSON with column names and types
    """
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    params = {"name": table_name}
    if schema:
        params["schema"] = schema
    result = _make_request("get", f"/api/v1/database/{database_id}/table_metadata/", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
def execute_sql(
    database_id: int,
    sql: str,
    schema: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """
    Execute SQL query in Superset SQL Lab.

    Args:
        database_id: Superset database ID
        sql: SQL query to execute
        schema: Optional schema name
        project_id: Project UUID — must own ``database_id`` in scoped mode

    Returns:
        JSON with query results (columns, data, row_count)
    """
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    payload = {
        "database_id": database_id,
        "sql": sql,
        "schema": schema or "",
        "tab": "MCP Query",
        "runAsync": False,
        "select_as_cta": False,
    }

    result = _make_request("post", "/api/v1/sqllab/execute/", data=payload)

    # Check for API error
    if result.get("__error__"):
        return json.dumps({
            "error": "SQL execution failed",
            "message": result.get("message", result.get("details", "Unknown error")),
            "details": result.get("details", ""),
        }, indent=2)

    # Normalize response
    if isinstance(result, dict):
        # Superset sqllab may return 200 but with error field
        if result.get("errors") or result.get("error"):
            err_msg = result.get("errors") or result.get("error")
            return json.dumps({
                "error": "SQL execution failed",
                "message": err_msg,
                "result": result,
            }, indent=2)
        data = result.get("data", [])
        columns = result.get("columns", [])
        return json.dumps({
            "columns": columns,
            "data": data,
            "row_count": len(data) if isinstance(data, list) else 0,
            "result": result,
        }, indent=2)

    return json.dumps(result, indent=2)


@mcp.tool()
def format_sql(sql: str) -> str:
    """
    Format a SQL query using Superset's SQL formatter for readability.

    Use this to pretty-print SQL before showing it to the user, or to normalize
    indentation/casing before calling execute_sql.

    Args:
        sql: Raw SQL string

    Returns:
        JSON with the formatted SQL, or an error dict.
    """
    _ensure_csrf()
    result = _make_request("post", "/api/v1/sqllab/format_sql", data={"sql": sql})
    if result.get("__error__"):
        return json.dumps({
            "error": "Failed to format SQL",
            "message": result.get("message", result.get("details", "Unknown error")),
        }, indent=2)
    return json.dumps(result, indent=2)


@mcp.tool()
def estimate_query_cost(
    database_id: int,
    sql: str,
    schema: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """
    Estimate the cost of a SQL query against a Superset database without executing it.

    Use before execute_sql on large tables to warn the user or decide whether to run.
    Only supported for engines that implement EXPLAIN cost (Presto/Trino, BigQuery, etc.);
    other backends may return an error.

    Args:
        database_id: Superset database id
        sql: SQL query to estimate
        schema: Optional schema name
        project_id: Project UUID — must own ``database_id`` in scoped mode

    Returns:
        JSON with estimated cost metrics from Superset, or an error dict.
    """
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    payload: dict = {"database_id": database_id, "sql": sql}
    if schema:
        payload["schema"] = schema
    _ensure_csrf()
    result = _make_request("post", "/api/v1/sqllab/estimate", data=payload)
    if result.get("__error__"):
        return json.dumps({
            "error": "Failed to estimate query cost",
            "message": result.get("message", result.get("details", "Unknown error")),
        }, indent=2)
    return json.dumps(result, indent=2)


@mcp.tool()
def validate_sql(
    database_id: int,
    sql: str,
    project_id: Optional[str] = None,
) -> str:
    """
    Validate SQL syntax against a Superset database without executing it.

    Call before execute_sql to catch syntax errors early. Returns a list of parse
    errors from the backend parser (empty list = valid).

    Args:
        database_id: Superset database id
        sql: SQL query to validate
        project_id: Project UUID — must own ``database_id`` in scoped mode

    Returns:
        JSON with validation errors (empty list = valid), or an error dict.
    """
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    _ensure_csrf()
    result = _make_request(
        "post",
        f"/api/v1/database/{database_id}/validate_sql/",
        data={"sql": sql},
    )
    if result.get("__error__"):
        return json.dumps({
            "error": "Failed to validate SQL",
            "message": result.get("message", result.get("details", "Unknown error")),
        }, indent=2)
    return json.dumps(result, indent=2)


import hashlib

@mcp.tool()
def create_virtual_dataset(
    database_id: int,
    table_name: str,
    sql: str,
    project_id: Optional[str] = None,
) -> str:
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    import hashlib
    sql_hash = hashlib.md5(sql.strip().lower().encode()).hexdigest()[:8]
    unique_name = f"{table_name}_{sql_hash}"

    _ensure_csrf()

    def _find_dataset(name: str):
        result = _make_request("get", "/api/v1/dataset/", params={"page_size": 100})
        if result.get("__error__"):
            return None
        for ds in result.get("result", []):
            if ds.get("table_name", "").lower() == name.lower():
                return ds
        return None

    # Check existing trước
    existing = _find_dataset(unique_name)
    if existing:
        logger.info(f"[Superset] Dataset '{unique_name}' already exists, reusing id {existing['id']}")
        return json.dumps({
            "id": existing["id"],
            "table_name": unique_name,
            "database_id": database_id,
            "status": "already_exists",
        }, indent=2)

    payload = {
        "database": database_id,
        "table_name": unique_name,
        "sql": sql,
        "is_managed_externally": False,
    }

    result = _make_request("post", "/api/v1/dataset/", data=payload)
    logger.info(f"[Superset] POST /api/v1/dataset/ response: {result}, payload: {payload}")

    if result.get("__error__"):
        status_code = result.get("status_code", 0)
        details = result.get("details", "")
        combined = (details + str(result.get("message", ""))).lower()

        # ✅ 422 "already exists" → fetch lại theo page_size lớn hơn
        if status_code == 422 or "already exists" in combined:
            logger.info(f"[Superset] Dataset '{unique_name}' exists (race), fetching all datasets...")
            retry = _make_request("get", "/api/v1/dataset/", params={"page_size": 100})
            for ds in retry.get("result", []):
                if ds.get("table_name", "").lower() == unique_name.lower():
                    return json.dumps({
                        "id": ds["id"],
                        "table_name": unique_name,
                        "database_id": database_id,
                        "status": "already_exists",
                    }, indent=2)

        return json.dumps({
            "error": "Virtual dataset creation failed",
            "message": result.get("message", result.get("details", "Unknown error")),
            "details": details,
        }, indent=2)

    dataset_id = result.get("id") or result.get("result", {}).get("id")

    return json.dumps({
        "id": dataset_id,
        "table_name": unique_name,
        "database_id": database_id,
        "status": "created",
    }, indent=2)

@mcp.tool()
def create_chart(
    slice_name: str,
    datasource_id: int,
    viz_type: str,
    params: str,
    project_id: Optional[str] = None,
) -> str:
    """
    Create a chart in Superset.

    Args:
        slice_name: Display name for the chart
        datasource_id: Dataset ID
        viz_type: Chart type (e.g., "bar", "line", "pie", "echarts_timeseries_line", "table")
        params: JSON string with chart configuration (datasource, metrics, groupby, etc.)
        project_id: Project UUID — must own the dataset's underlying database in scoped mode

    Returns:
        JSON with chart id and explore URL
    """
    deny = _check_dataset_scope(datasource_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    # Parse params if string
    if isinstance(params, str):
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError:
            params_dict = {}
    else:
        params_dict = params

    # Build params with datasource
    full_params = params_dict.copy()
    full_params["datasource"] = f"{datasource_id}__table"
    full_params["viz_type"] = viz_type

    payload = {
        "slice_name": slice_name,
        "datasource_id": datasource_id,
        "datasource_type": "table",
        "viz_type": viz_type,
        "params": json.dumps(full_params),
    }

    # Try to get current user for owner assignment
    try:
        user_info = _make_request("get", "/api/v1/me/")
        if not user_info.get("__error__"):
            user_id = None
            user_result = user_info.get("result", user_info)
            if isinstance(user_result, dict):
                user_id = user_result.get("id")
            if user_id:
                payload["owners"] = [user_id]
    except Exception:
        pass

    _ensure_csrf()
    result = _make_request("post", "/api/v1/chart/", data=payload)

    # Check for API error
    if result.get("__error__"):
        return json.dumps({
            "error": "Chart creation failed",
            "message": result.get("message", result.get("details", "Unknown error")),
            "details": result.get("details", ""),
        }, indent=2)

    chart_id = None
    if "id" in result:
        chart_id = result["id"]
    elif "result" in result and isinstance(result["result"], dict):
        chart_id = result["result"].get("id")

    chart_url = f"{SUPERSET_URL}/superset/explore/?slice_id={chart_id}"
    logger.info(f"[Superset] Chart created: {chart_id} - {chart_url}")

    return json.dumps({
        "id": chart_id,
        "slice_name": slice_name,
        "viz_type": viz_type,
        "datasource_id": datasource_id,
        "status": "created",
        "explore_url": chart_url,
    }, indent=2)


@mcp.tool()
def get_chart_embed_url(chart_id: int, project_id: Optional[str] = None) -> str:
    """
    Get the Superset explore URL for embedding a chart as iframe.

    Args:
        chart_id: Chart ID in Superset
        project_id: Project UUID — must own the chart's underlying database in scoped mode

    Returns:
        Superset explore URL
    """
    deny = _check_chart_scope(chart_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    # Get chart details
    chart_info = _make_request("get", f"/api/v1/chart/{chart_id}")

    chart_data = chart_info
    if isinstance(chart_info, dict):
        chart_data = chart_info.get("result", chart_info)

    slice_id = chart_id
    datasource_id = chart_data.get("datasource_id") if isinstance(chart_data, dict) else None
    viz_type = chart_data.get("viz_type") if isinstance(chart_data, dict) else "bar"

    # Build form_data for the explore URL
    form_data = {
        "slice_id": slice_id,
        "datasource": f"{datasource_id}__table" if datasource_id else None,
        "viz_type": viz_type,
    }

    # Clean None values
    form_data = {k: v for k, v in form_data.items() if v is not None}

    # Create form_data key
    try:
        _ensure_csrf()
        form_data_response = _make_request(
            "post",
            "/api/v1/explore/form_data",
            data={
                "datasource_id": datasource_id,
                "datasource_type": "table",
                "form_data": json.dumps(form_data),
            },
        )
        form_data_key = None
        if isinstance(form_data_response, dict):
            form_data_key = form_data_response.get("key")
        if form_data_key:
            explore_url = f"{SUPERSET_URL}/explore/?form_data_key={form_data_key}&slice_id={slice_id}"
        else:
            explore_url = f"{SUPERSET_URL}/superset/explore/?slice_id={slice_id}"
    except Exception:
        explore_url = f"{SUPERSET_URL}/superset/explore/?slice_id={slice_id}"

    logger.info(f"[Superset] Chart embed URL: {explore_url}")
    return json.dumps({
        "chart_id": chart_id,
        "embed_url": explore_url,
        "fullscreen_url": f"{SUPERSET_URL}/superset/explore/?slice_id={slice_id}",
    }, indent=2)


@mcp.tool()
def wrap_chart_in_dashboard(chart_id: int, project_id: Optional[str] = None) -> str:
    """
    Wrap a chart in a single-chart dashboard and enable embedding.

    Superset Guest Tokens target dashboards (not standalone charts), so to embed
    a chart via guest token we put it inside a 1-chart dashboard and expose its
    ``embedded_uuid``. Idempotent by title ``chart_<id>_p<project_id>``.

    Args:
        chart_id: Chart ID to wrap
        project_id: Project UUID — must own the chart in scoped mode

    Returns:
        JSON with dashboard_id, embedded_uuid, status
    """
    deny = _check_chart_scope(chart_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    title = f"chart_{chart_id}_p{project_id or 'global'}"

    existing = _make_request(
        "get",
        "/api/v1/dashboard/",
        params={"q": f"(filters:!((col:dashboard_title,opr:eq,value:'{title}')))"},
    )
    dash_id: Optional[int] = None
    if not existing.get("__error__"):
        for d in (existing.get("result") or []):
            if isinstance(d, dict) and d.get("dashboard_title") == title:
                dash_id = d.get("id")
                break

    if dash_id is None:
        position = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
            "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-1"], "parents": ["ROOT_ID"]},
            "ROW-1": {
                "type": "ROW",
                "id": "ROW-1",
                "children": [f"CHART-{chart_id}"],
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            },
            f"CHART-{chart_id}": {
                "type": "CHART",
                "id": f"CHART-{chart_id}",
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", "ROW-1"],
                "meta": {"width": 12, "height": 50, "chartId": chart_id},
            },
        }
        _ensure_csrf()
        created = _make_request(
            "post",
            "/api/v1/dashboard/",
            data={
                "dashboard_title": title,
                "published": True,
                "position_json": json.dumps(position),
            },
        )
        if created.get("__error__"):
            return json.dumps({
                "error": "Failed to create wrapper dashboard",
                "message": created.get("message", created.get("details", "Unknown")),
            }, indent=2)
        dash_id = created.get("id") or (created.get("result") or {}).get("id")

    # Link chart to dashboard. PUT /api/v1/chart with {"dashboards": [...]}
    # was tried first but it WIPES `datasource_id` (FAB PUT replaces the record
    # rather than merging), leaving the chart unrenderable. Read the chart's
    # current datasource and replay it alongside the dashboard linkage so the
    # binding survives.
    if dash_id is not None:
        _ensure_csrf()
        existing_charts = _make_request("get", f"/api/v1/dashboard/{dash_id}/charts")
        already_linked = any(
            (c or {}).get("id") == chart_id
            for c in (existing_charts.get("result") or [])
        )
        if not already_linked:
            chart_get = _make_request("get", f"/api/v1/chart/{chart_id}")
            chart_data = (chart_get.get("result") or {}) if not chart_get.get("__error__") else {}
            datasource_id = chart_data.get("datasource_id")
            datasource_type = chart_data.get("datasource_type") or "table"
            put_body: dict = {"dashboards": [dash_id]}
            if datasource_id is not None:
                put_body["datasource_id"] = datasource_id
                put_body["datasource_type"] = datasource_type
            chart_put = _make_request(
                "put",
                f"/api/v1/chart/{chart_id}",
                data=put_body,
            )
            if chart_put.get("__error__"):
                logger.warning(
                    f"[Superset] Failed to attach chart {chart_id} to dashboard "
                    f"{dash_id}: {chart_put.get('details')}"
                )

    if dash_id is None:
        return json.dumps({"error": "Could not resolve dashboard id"}, indent=2)

    # Enable embedding. ``allowed_domains`` MUST list the parent window origin —
    # empty means "block all" and breaks the postMessage handshake.
    _ensure_csrf()
    embed_resp = _make_request(
        "post",
        f"/api/v1/dashboard/{dash_id}/embedded",
        data={"allowed_domains": EMBED_ALLOWED_DOMAINS},
    )
    embedded_uuid: Optional[str] = None
    if not embed_resp.get("__error__"):
        record = embed_resp.get("result") or embed_resp
        if isinstance(record, dict):
            embedded_uuid = record.get("uuid") or record.get("embedded_uuid")
    if not embedded_uuid:
        get_resp = _make_request("get", f"/api/v1/dashboard/{dash_id}/embedded")
        if not get_resp.get("__error__"):
            record = get_resp.get("result") or get_resp
            if isinstance(record, dict):
                embedded_uuid = record.get("uuid") or record.get("embedded_uuid")
    # Always PUT to repair stale allowed_domains (idempotent)
    if embedded_uuid:
        try:
            _make_request(
                "put",
                f"/api/v1/dashboard/{dash_id}/embedded",
                data={"allowed_domains": EMBED_ALLOWED_DOMAINS},
            )
        except Exception as e:
            logger.warning(f"[Superset] Failed to update allowed_domains for dash {dash_id}: {e}")

    return json.dumps({
        "dashboard_id": dash_id,
        "dashboard_title": title,
        "embedded_uuid": embedded_uuid,
        "chart_id": chart_id,
    }, indent=2)


@mcp.tool()
def mint_guest_token(
    embedded_uuid: str,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    ttl_seconds: int = 300,
) -> str:
    """
    Mint a short-lived Superset Guest Token scoped to one embedded dashboard.

    Returns:
        JSON with token, ttl_seconds, embed_url, embedded_uuid, supersetDomain
    """
    if not embedded_uuid:
        return _scope_violation("embedded_uuid required")

    payload = {
        "user": {
            "username": f"guest_{user_id or 'anon'}_{project_id or 'global'}"[:50],
            "first_name": "Guest",
            "last_name": (user_id or "anon")[:64],
        },
        "resources": [{"type": "dashboard", "id": embedded_uuid}],
        "rls": [],
    }

    _ensure_csrf()
    result = _make_request("post", "/api/v1/security/guest_token/", data=payload)
    if result.get("__error__"):
        return json.dumps({
            "error": "Failed to mint guest token",
            "message": result.get("message", result.get("details", "Unknown error")),
        }, indent=2)

    token = result.get("token") if isinstance(result, dict) else None
    if not token:
        return json.dumps({"error": "Guest token missing in response", "raw": result}, indent=2)

    return json.dumps({
        "token": token,
        "ttl_seconds": ttl_seconds,
        "embed_url": f"{SUPERSET_URL}/embedded/{embedded_uuid}",
        "supersetDomain": SUPERSET_URL,
        "embedded_uuid": embedded_uuid,
    }, indent=2)


@mcp.tool()
def list_charts(project_id: Optional[str] = None) -> str:
    """
    List charts in Superset, scoped to the caller's project.

    Args:
        project_id: When set, only charts whose dataset's database is named
            after ``project_id`` are returned.

    Returns:
        JSON list of charts
    """
    if not project_id and REQUIRE_PROJECT_ID:
        return _scope_violation("project_id required to list charts")

    result = _make_request("get", "/api/v1/chart/")
    charts = result.get("result", []) if isinstance(result, dict) else []

    if project_id:
        # Filter charts to those whose dataset belongs to this project's DB.
        # Each filter call hits the dataset cache (TTL 60s) so listing all charts
        # is O(N) tool API calls only on cold cache.
        filtered = []
        for c in charts:
            if not isinstance(c, dict):
                continue
            ds_id = c.get("datasource_id")
            if ds_id is None:
                continue
            try:
                if _check_dataset_scope(int(ds_id), project_id) is None:
                    filtered.append(c)
            except (TypeError, ValueError):
                continue
        charts = filtered

    return json.dumps(charts, indent=2)


@mcp.tool()
def get_chart(chart_id: int, project_id: Optional[str] = None) -> str:
    """
    Get chart details by ID.

    Args:
        chart_id: Chart ID
        project_id: Project UUID — must own the chart's underlying database in scoped mode

    Returns:
        JSON chart details
    """
    deny = _check_chart_scope(chart_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)

    result = _make_request("get", f"/api/v1/chart/{chart_id}")
    return json.dumps(result, indent=2)


@mcp.tool()
def superset_diagnose_embed_access(project_id: str) -> str:
    """
    Diagnose why an unauthenticated browser can't render the chart iframe.

    Inspects the embed-view role (Public, inheriting Gamma via PUBLIC_ROLE_LIKE),
    the project DB's PVM, and whether the role has database_access on the DB.
    Use when chart iframe returns 403.

    Args:
        project_id: UUID of the project to diagnose

    Returns:
        JSON report with role_id, role_perms_count, db_pvm_id, granted, suggestions.
    """
    report: dict = {"project_id": project_id, "embed_view_role": GUEST_ROLE_NAME}

    # 1) Find DB by name == project_id
    dbs = _make_request("get", "/api/v1/database/", params={"page_size": 100})
    db_id: Optional[int] = None
    for db in (dbs.get("result") or []):
        if isinstance(db, dict) and db.get("database_name") == project_id:
            db_id = db.get("id")
            break
    report["db_id"] = db_id
    if db_id is None:
        report["error"] = f"DB named '{project_id}' not found in Superset"
        return json.dumps(report, indent=2)

    # 2) Find role
    roles = _make_request("get", "/api/v1/security/roles/", params={"page_size": 100})
    role_id: Optional[int] = None
    role_perms: list = []
    for r in (roles.get("result") or []):
        if isinstance(r, dict) and r.get("name") == GUEST_ROLE_NAME:
            role_id = r.get("id")
            break
    report["role_id"] = role_id
    if role_id is None:
        report["error"] = f"Role '{GUEST_ROLE_NAME}' not found"
        report["available_roles"] = [r.get("name") for r in (roles.get("result") or []) if isinstance(r, dict)]
        return json.dumps(report, indent=2)

    role_detail = _make_request("get", f"/api/v1/security/roles/{role_id}")
    rec = role_detail.get("result") or role_detail
    if isinstance(rec, dict):
        role_perms = rec.get("permissions") or []
    role_perm_ids = [p.get("id") for p in role_perms if isinstance(p, dict)]
    report["role_perms_count"] = len(role_perm_ids)

    # 3) Find PVM (database_access on this DB) by scanning
    target_view = f"[{project_id}].(id:{db_id})"
    target_pvm_id: Optional[int] = None
    page = 0
    while page <= 50:
        pvms = _make_request(
            "get", "/api/v1/security/permissions-resources/",
            params={"page": page, "page_size": 100},
        )
        results = pvms.get("result") or []
        if not results:
            break
        for pv in results:
            if not isinstance(pv, dict):
                continue
            perm = pv.get("permission")
            view = pv.get("view_menu")
            perm_name = perm.get("name") if isinstance(perm, dict) else perm
            view_name = view.get("name") if isinstance(view, dict) else view
            if perm_name == "database_access" and view_name == target_view:
                target_pvm_id = pv.get("id")
                break
        if target_pvm_id is not None or len(results) < 100:
            break
        page += 1
    report["target_pvm"] = {"id": target_pvm_id, "view_menu": target_view}

    if target_pvm_id is None:
        report["error"] = (
            f"PVM 'database_access on {target_view}' does not exist in Superset. "
            "Superset auto-creates this when registering DB; try unregister + re-register."
        )
        return json.dumps(report, indent=2)

    granted = target_pvm_id in role_perm_ids
    report["granted"] = granted

    if not granted:
        report["suggestion"] = (
            f"Run register_database again with project_id='{project_id}' to trigger "
            f"_grant_database_to_guest_role(), or PUT /api/v1/security/roles/{role_id} "
            f"with permissions=existing+[{target_pvm_id}]."
        )
    else:
        report["suggestion"] = (
            "Grant looks correct. If still 403, check (1) Superset restarted after "
            "config change, (2) PUBLIC_ROLE_LIKE = 'Gamma' is set so Public has read "
            "perms, (3) chart's underlying dataset/chart still exists."
        )
    return json.dumps(report, indent=2)


@mcp.tool()
def superset_grant_database(project_id: str) -> str:
    """
    Manually trigger the database_access grant for a project.

    Useful when register_database was called before the grant feature shipped,
    or to repair a DB whose grant silently failed.

    Args:
        project_id: UUID of the project

    Returns:
        JSON status from the grant operation.
    """
    dbs = _make_request("get", "/api/v1/database/", params={"page_size": 100})
    for db in (dbs.get("result") or []):
        if isinstance(db, dict) and db.get("database_name") == project_id:
            db_id = db.get("id")
            if not isinstance(db_id, int):
                return json.dumps({"error": "DB id missing"}, indent=2)
            _grant_database_to_guest_role(db_id, project_id)
            return json.dumps({
                "status": "grant_attempted",
                "project_id": project_id,
                "db_id": db_id,
                "note": "Check MCP server logs for [Superset] Grant: lines.",
            }, indent=2)
    return json.dumps({"error": f"DB named '{project_id}' not found"}, indent=2)


@mcp.tool()
def superset_lookup_embedded(embedded_uuid: str) -> str:
    """
    Verify an embedded_uuid exists in Superset's embedded dashboard registry.

    Use this when ``/embedded/<uuid>`` returns "Page not found" to determine
    whether the cause is (a) embed config never written to DB, or (b) the
    EMBEDDED_SUPERSET feature flag is off so the route handler is missing.

    Args:
        embedded_uuid: The UUID returned by wrap_chart_in_dashboard

    Returns:
        JSON with the embedded config (dashboard_id, allowed_domains, ...)
        or an error if not found.
    """
    result = _make_request("get", f"/api/v1/embedded_dashboard/{embedded_uuid}")
    if result.get("__error__"):
        return json.dumps({
            "exists": False,
            "embedded_uuid": embedded_uuid,
            "status_code": result.get("status_code"),
            "message": result.get("message", result.get("details", "Unknown")),
            "diagnosis": (
                "404 → embed config NOT in DB; wrap_chart_in_dashboard didn't persist. "
                "401/403 → admin token issue. "
                "If config exists but /embedded/<uuid> shows 'Page not found' in browser, "
                "the EMBEDDED_SUPERSET feature flag is not active — restart Superset."
            ),
        }, indent=2)
    return json.dumps({
        "exists": True,
        "embedded_uuid": embedded_uuid,
        "data": result,
    }, indent=2)


@mcp.tool()
def superset_status() -> str:
    """
    Check Superset connection status and authentication.

    Returns:
        Status info
    """
    try:
        token_data = _load_token()
        if token_data and _is_token_valid(token_data):
            # Verify token works
            me = _make_request("get", "/api/v1/me/")
            username = "unknown"
            if isinstance(me, dict):
                user_result = me.get("result", me)
                if isinstance(user_result, dict):
                    username = user_result.get("username", "unknown")
            return json.dumps({
                "status": "connected",
                "authenticated_as": username,
                "superset_url": SUPERSET_URL,
            }, indent=2)
        else:
            return json.dumps({"status": "not_authenticated", "superset_url": SUPERSET_URL})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e), "superset_url": SUPERSET_URL})


# ==================== Dashboard Embed Management ====================


@mcp.tool()
def revoke_dashboard_embedded(dashboard_id: int) -> str:
    """
    Disable embedding on a dashboard, invalidating its ``embedded_uuid``.

    Use to "unshare" a chart that was previously wrapped + embedded. After this
    call, any iframe still using the old uuid will 404 and existing guest tokens
    for the dashboard will be rejected on next use.

    Args:
        dashboard_id: The dashboard's numeric ID (NOT the embedded_uuid)

    Returns:
        JSON status from Superset.
    """
    _ensure_csrf()
    result = _make_request("delete", f"/api/v1/dashboard/{dashboard_id}/embedded")
    if result.get("__error__"):
        return json.dumps({
            "error": "Failed to revoke embedded config",
            "message": result.get("message", result.get("details", "Unknown")),
            "status_code": result.get("status_code"),
        }, indent=2)
    return json.dumps({"status": "revoked", "dashboard_id": dashboard_id, **result}, indent=2)


# ==================== Annotation Layers ====================
# Annotation layers overlay text/event markers on time-series charts.
# Hierarchy: AnnotationLayer (container) → Annotation (item with start/end time).


@mcp.tool()
def list_annotation_layers(page: int = 0, page_size: int = 100) -> str:
    """List annotation layers (paginated)."""
    result = _make_request(
        "get", "/api/v1/annotation_layer/",
        params={"page": page, "page_size": page_size},
    )
    if result.get("__error__"):
        return json.dumps({"error": result.get("message")}, indent=2)
    return json.dumps(result.get("result", []), indent=2)


@mcp.tool()
def get_annotation_layer(layer_id: int) -> str:
    """Get a single annotation layer by id."""
    result = _make_request("get", f"/api/v1/annotation_layer/{layer_id}")
    return json.dumps(result, indent=2)


@mcp.tool()
def create_annotation_layer(name: str, description: str = "") -> str:
    """Create a new annotation layer (container for annotations)."""
    _ensure_csrf()
    result = _make_request(
        "post", "/api/v1/annotation_layer/",
        data={"name": name, "descr": description},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def update_annotation_layer(layer_id: int, name: Optional[str] = None, description: Optional[str] = None) -> str:
    """Update an annotation layer's name/description."""
    payload: dict = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["descr"] = description
    if not payload:
        return _scope_violation("nothing to update")
    _ensure_csrf()
    result = _make_request("put", f"/api/v1/annotation_layer/{layer_id}", data=payload)
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_annotation_layer(layer_id: int) -> str:
    """Delete an annotation layer (and all its annotations)."""
    _ensure_csrf()
    result = _make_request("delete", f"/api/v1/annotation_layer/{layer_id}")
    return json.dumps(result, indent=2) if not result.get("__error__") else json.dumps(
        {"error": result.get("message")}, indent=2
    )


@mcp.tool()
def list_annotations(layer_id: int, page: int = 0, page_size: int = 100) -> str:
    """List annotations within a layer."""
    result = _make_request(
        "get", f"/api/v1/annotation_layer/{layer_id}/annotation/",
        params={"page": page, "page_size": page_size},
    )
    if result.get("__error__"):
        return json.dumps({"error": result.get("message")}, indent=2)
    return json.dumps(result.get("result", []), indent=2)


@mcp.tool()
def create_annotation(
    layer_id: int,
    short_descr: str,
    start_dttm: str,
    end_dttm: str,
    long_descr: str = "",
    json_metadata: str = "",
) -> str:
    """
    Create an annotation (event marker) inside a layer.

    Args:
        layer_id: Parent annotation layer id
        short_descr: Short label shown on chart hover
        start_dttm: ISO8601 start time, e.g. "2024-01-15T00:00:00"
        end_dttm: ISO8601 end time
        long_descr: Optional longer description
        json_metadata: Optional JSON string with extra metadata
    """
    _ensure_csrf()
    payload = {
        "short_descr": short_descr,
        "long_descr": long_descr,
        "start_dttm": start_dttm,
        "end_dttm": end_dttm,
    }
    if json_metadata:
        payload["json_metadata"] = json_metadata
    result = _make_request(
        "post", f"/api/v1/annotation_layer/{layer_id}/annotation/",
        data=payload,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_annotation(layer_id: int, annotation_id: int) -> str:
    """Delete a single annotation from a layer."""
    _ensure_csrf()
    result = _make_request(
        "delete", f"/api/v1/annotation_layer/{layer_id}/annotation/{annotation_id}",
    )
    return json.dumps(result, indent=2) if not result.get("__error__") else json.dumps(
        {"error": result.get("message")}, indent=2
    )


# ==================== CSS Templates ====================


@mcp.tool()
def list_css_templates(page: int = 0, page_size: int = 100) -> str:
    """List custom CSS templates available for dashboard styling."""
    result = _make_request(
        "get", "/api/v1/css_template/",
        params={"page": page, "page_size": page_size},
    )
    if result.get("__error__"):
        return json.dumps({"error": result.get("message")}, indent=2)
    return json.dumps(result.get("result", []), indent=2)


@mcp.tool()
def get_css_template(template_id: int) -> str:
    """Get a CSS template by id."""
    result = _make_request("get", f"/api/v1/css_template/{template_id}")
    return json.dumps(result, indent=2)


@mcp.tool()
def create_css_template(template_name: str, css: str) -> str:
    """Create a CSS template that can be applied to dashboards."""
    _ensure_csrf()
    result = _make_request(
        "post", "/api/v1/css_template/",
        data={"template_name": template_name, "css": css},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def update_css_template(template_id: int, template_name: Optional[str] = None, css: Optional[str] = None) -> str:
    """Update a CSS template."""
    payload: dict = {}
    if template_name is not None:
        payload["template_name"] = template_name
    if css is not None:
        payload["css"] = css
    if not payload:
        return _scope_violation("nothing to update")
    _ensure_csrf()
    result = _make_request("put", f"/api/v1/css_template/{template_id}", data=payload)
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_css_template(template_id: int) -> str:
    """Delete a CSS template."""
    _ensure_csrf()
    result = _make_request("delete", f"/api/v1/css_template/{template_id}")
    return json.dumps(result, indent=2) if not result.get("__error__") else json.dumps(
        {"error": result.get("message")}, indent=2
    )


# ==================== Saved Queries (SQL Lab) ====================


@mcp.tool()
def list_saved_queries(page: int = 0, page_size: int = 100) -> str:
    """List saved SQL Lab queries."""
    result = _make_request(
        "get", "/api/v1/saved_query/",
        params={"page": page, "page_size": page_size},
    )
    if result.get("__error__"):
        return json.dumps({"error": result.get("message")}, indent=2)
    return json.dumps(result.get("result", []), indent=2)


@mcp.tool()
def get_saved_query(query_id: int) -> str:
    """Get a saved query by id."""
    result = _make_request("get", f"/api/v1/saved_query/{query_id}")
    return json.dumps(result, indent=2)


@mcp.tool()
def create_saved_query(
    database_id: int,
    label: str,
    sql: str,
    description: str = "",
    schema: str = "",
    project_id: Optional[str] = None,
) -> str:
    """
    Save a SQL query in SQL Lab.

    Args:
        database_id: The DB this query targets (must be in scope)
        label: Display name
        sql: The SQL string
        description: Optional description
        schema: Optional schema name
        project_id: Project UUID — must own ``database_id`` in scoped mode
    """
    deny = _check_db_scope(database_id, project_id)
    if deny:
        return json.dumps(deny, indent=2)
    _ensure_csrf()
    payload = {
        "db_id": database_id,
        "label": label,
        "sql": sql,
        "description": description,
        "schema": schema,
    }
    result = _make_request("post", "/api/v1/saved_query/", data=payload)
    return json.dumps(result, indent=2)


@mcp.tool()
def update_saved_query(
    query_id: int,
    label: Optional[str] = None,
    sql: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[str] = None,
) -> str:
    """Update a saved query."""
    payload: dict = {}
    for k, v in (("label", label), ("sql", sql), ("description", description), ("schema", schema)):
        if v is not None:
            payload[k] = v
    if not payload:
        return _scope_violation("nothing to update")
    _ensure_csrf()
    result = _make_request("put", f"/api/v1/saved_query/{query_id}", data=payload)
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_saved_query(query_id: int) -> str:
    """Delete a saved query."""
    _ensure_csrf()
    result = _make_request("delete", f"/api/v1/saved_query/{query_id}")
    return json.dumps(result, indent=2) if not result.get("__error__") else json.dumps(
        {"error": result.get("message")}, indent=2
    )


# ==================== Reports & Alerts ====================
# Superset's "report" resource covers both scheduled reports (email/Slack a
# dashboard or chart at cron times) and alerts (notify when a metric crosses
# a threshold). Type is selected via the ``type`` field: "Report" | "Alert".


@mcp.tool()
def list_reports(page: int = 0, page_size: int = 100) -> str:
    """List scheduled reports and alerts."""
    result = _make_request(
        "get", "/api/v1/report/",
        params={"page": page, "page_size": page_size},
    )
    if result.get("__error__"):
        return json.dumps({"error": result.get("message")}, indent=2)
    return json.dumps(result.get("result", []), indent=2)


@mcp.tool()
def get_report(report_id: int) -> str:
    """Get a report/alert configuration by id."""
    result = _make_request("get", f"/api/v1/report/{report_id}")
    return json.dumps(result, indent=2)


@mcp.tool()
def create_report(
    name: str,
    crontab: str,
    report_type: str = "Report",
    description: str = "",
    dashboard_id: Optional[int] = None,
    chart_id: Optional[int] = None,
    recipients_json: str = "[]",
    extra_json: str = "{}",
) -> str:
    """
    Create a scheduled report or alert.

    Args:
        name: Display name
        crontab: Cron expression, e.g. "0 9 * * MON" for 9am every Monday
        report_type: "Report" (scheduled send) or "Alert" (threshold-based)
        description: Optional description
        dashboard_id: Target a dashboard (or pass chart_id instead)
        chart_id: Target a chart
        recipients_json: JSON array of recipient configs, e.g.
            '[{"type":"Email","recipient_config_json":"{\\"target\\":\\"a@b.com\\"}"}]'
        extra_json: JSON object with extra fields (validator_type, validator_config_json,
            sql for alerts, working_timeout, grace_period, etc.)

    Returns:
        JSON with the created report id.
    """
    if not dashboard_id and not chart_id:
        return _scope_violation("either dashboard_id or chart_id is required")
    _ensure_csrf()
    payload: dict = {
        "name": name,
        "type": report_type,
        "crontab": crontab,
        "description": description,
        "active": True,
    }
    if dashboard_id is not None:
        payload["dashboard"] = dashboard_id
    if chart_id is not None:
        payload["chart"] = chart_id
    try:
        recips = json.loads(recipients_json) if recipients_json else []
        if isinstance(recips, list):
            payload["recipients"] = recips
    except Exception:
        pass
    try:
        extra = json.loads(extra_json) if extra_json else {}
        if isinstance(extra, dict):
            payload.update(extra)
    except Exception:
        pass
    result = _make_request("post", "/api/v1/report/", data=payload)
    return json.dumps(result, indent=2)


@mcp.tool()
def update_report(report_id: int, payload_json: str) -> str:
    """
    Update a report/alert. Pass the fields to change as a JSON object string.

    Args:
        report_id: Report id
        payload_json: JSON object with fields like {"name":"...","crontab":"...","active":false}
    """
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        return _scope_violation("payload_json must be valid JSON")
    if not isinstance(payload, dict) or not payload:
        return _scope_violation("payload_json must be a non-empty object")
    _ensure_csrf()
    result = _make_request("put", f"/api/v1/report/{report_id}", data=payload)
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_report(report_id: int) -> str:
    """Delete a report or alert."""
    _ensure_csrf()
    result = _make_request("delete", f"/api/v1/report/{report_id}")
    return json.dumps(result, indent=2) if not result.get("__error__") else json.dumps(
        {"error": result.get("message")}, indent=2
    )


def main():
    """Run the Superset MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
