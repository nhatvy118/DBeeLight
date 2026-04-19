"""
Superset MCP Tools - FastMCP server for Apache Superset visualization.

Provides tools for authenticating with Superset, managing database connections,
executing SQL queries, creating virtual datasets, and building charts.
"""

import json
import logging
import os
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
def list_superset_databases() -> str:
    """
    List all databases registered in Superset.

    Returns:
        JSON list of databases with id, name, backend
    """
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
    return json.dumps(databases, indent=2)


@mcp.tool()
def register_database(name: str, sqlalchemy_uri: str, password: Optional[str] = None) -> str:
    """
    Register a new database connection in Superset, or return existing if name matches.

    Args:
        name: Display name for the database
        sqlalchemy_uri: SQLAlchemy connection URI
        password: Optional database password (for masking in URI)

    Returns:
        JSON with database id and status
    """
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

    return json.dumps({
        "id": db_id,
        "database_name": name,
        "status": "created",
        "message": f"Database '{name}' registered successfully",
        "sqlalchemy_uri": masked_uri,
    })


@mcp.tool()
def get_database_tables(database_id: int, schema: Optional[str] = None) -> str:
    """
    Get all tables in a Superset database.

    Args:
        database_id: Superset database ID
        schema: Optional schema name

    Returns:
        JSON list of table names
    """
    # Rison q: omit entirely when no schema (SQLite has no schema concept).
    # "(schema_name:)" with an empty value is invalid Rison and Superset rejects it with 400.
    params = {"q": f"(schema_name:{schema})"} if schema else {}
    result = _make_request("get", f"/api/v1/database/{database_id}/tables/", params=params)
    tables = result.get("result", [])
    return json.dumps(tables, indent=2)


@mcp.tool()
def get_table_metadata(database_id: int, table_name: str, schema: Optional[str] = None) -> str:
    """
    Get column metadata for a table.

    Args:
        database_id: Superset database ID
        table_name: Table name
        schema: Optional schema name

    Returns:
        JSON with column names and types
    """
    params = {"name": table_name}
    if schema:
        params["schema"] = schema
    result = _make_request("get", f"/api/v1/database/{database_id}/table_metadata/", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
def execute_sql(database_id: int, sql: str, schema: Optional[str] = None) -> str:
    """
    Execute SQL query in Superset SQL Lab.

    Args:
        database_id: Superset database ID
        sql: SQL query to execute
        schema: Optional schema name

    Returns:
        JSON with query results (columns, data, row_count)
    """
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
def estimate_query_cost(database_id: int, sql: str, schema: Optional[str] = None) -> str:
    """
    Estimate the cost of a SQL query against a Superset database without executing it.

    Use before execute_sql on large tables to warn the user or decide whether to run.
    Only supported for engines that implement EXPLAIN cost (Presto/Trino, BigQuery, etc.);
    other backends may return an error.

    Args:
        database_id: Superset database id
        sql: SQL query to estimate
        schema: Optional schema name

    Returns:
        JSON with estimated cost metrics from Superset, or an error dict.
    """
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
def validate_sql(database_id: int, sql: str) -> str:
    """
    Validate SQL syntax against a Superset database without executing it.

    Call before execute_sql to catch syntax errors early. Returns a list of parse
    errors from the backend parser (empty list = valid).

    Args:
        database_id: Superset database id
        sql: SQL query to validate

    Returns:
        JSON with validation errors (empty list = valid), or an error dict.
    """
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
def create_virtual_dataset(database_id: int, table_name: str, sql: str) -> str:
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
) -> str:
    """
    Create a chart in Superset.

    Args:
        slice_name: Display name for the chart
        datasource_id: Dataset ID
        viz_type: Chart type (e.g., "bar", "line", "pie", "echarts_timeseries_line", "table")
        params: JSON string with chart configuration (datasource, metrics, groupby, etc.)

    Returns:
        JSON with chart id and explore URL
    """
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
def get_chart_embed_url(chart_id: int) -> str:
    """
    Get the Superset explore URL for embedding a chart as iframe.

    Args:
        chart_id: Chart ID in Superset

    Returns:
        Superset explore URL
    """
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
def list_charts() -> str:
    """
    List all charts in Superset.

    Returns:
        JSON list of charts
    """
    result = _make_request("get", "/api/v1/chart/")
    charts = result.get("result", []) if isinstance(result, dict) else []
    return json.dumps(charts, indent=2)


@mcp.tool()
def get_chart(chart_id: int) -> str:
    """
    Get chart details by ID.

    Args:
        chart_id: Chart ID

    Returns:
        JSON chart details
    """
    result = _make_request("get", f"/api/v1/chart/{chart_id}")
    return json.dumps(result, indent=2)


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


def main():
    """Run the Superset MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
