"""
Superset configuration for mcp-server visualization backend.

This config connects Superset to:
- PostgreSQL for metadata storage
- Redis for caching and Celery
- Enables CORS for iframe embedding from the frontend
"""

import logging
import os
from datetime import timedelta

from celery.schedules import crontab
from flask_caching.backends.filesystemcache import FileSystemCache

logger = logging.getLogger()

# ==================== Database ====================
# PostgreSQL for Superset metadata (users, charts, datasets, database connections)

DATABASE_DIALECT = os.getenv("DATABASE_DIALECT", "postgresql+psycopg2")
DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "postgres")
DATABASE_HOST = os.getenv("DATABASE_HOST", "host.docker.internal")
DATABASE_PORT = os.getenv("DATABASE_PORT", "5432")
DATABASE_DB = os.getenv("SUPERSET_DB", "superset")

SQLALCHEMY_DATABASE_URI = (
    f"{DATABASE_DIALECT}://"
    f"{DATABASE_USER}:{DATABASE_PASSWORD}@"
    f"{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_DB}"
)

# ==================== Redis / Celery ====================

REDIS_HOST = os.getenv("REDIS_HOST", "superset-redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CELERY_DB = int(os.getenv("REDIS_CELERY_DB", "0"))
REDIS_RESULTS_DB = int(os.getenv("REDIS_RESULTS_DB", "1"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "redis_pass_123")

RESULTS_BACKEND = FileSystemCache("/app/superset_home/sqllab")

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_HOST": REDIS_HOST,
    "CACHE_REDIS_PORT": REDIS_PORT,
    "CACHE_REDIS_DB": REDIS_RESULTS_DB,
    "CACHE_REDIS_PASSWORD": REDIS_PASSWORD,
}
DATA_CACHE_CONFIG = CACHE_CONFIG
THUMBNAIL_CACHE_CONFIG = CACHE_CONFIG


class CeleryConfig:
    broker_url = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_CELERY_DB}"
    result_backend = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_RESULTS_DB}"
    imports = (
        "superset.sql_lab",
        "superset.tasks.scheduler",
        "superset.tasks.thumbnails",
        "superset.tasks.cache",
    )
    worker_prefetch_multiplier = 1
    task_acks_late = False
    beat_schedule = {
        "reports.scheduler": {
            "task": "reports.scheduler",
            "schedule": crontab(minute="*", hour="*"),
        },
        "reports.prune_log": {
            "task": "reports.prune_log",
            "schedule": crontab(minute=10, hour=0),
        },
    }


CELERY_CONFIG = CeleryConfig

# ==================== Security & Auth ====================

SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "CHANGE-THIS-IN-PRODUCTION")

# AUTH_DB - supports both session cookies and Bearer token authentication
AUTH_TYPE = 1
SESSION_COOKIE_NAME = 'superset_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False
PERMANENT_SESSION_LIFETIME = 3600

# JWT Configuration
AUTH_USER_REGISTRATION = False
AUTH_USER_REGISTRATION_ROLE = "Public"

from datetime import timedelta
JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

JWT_TOKEN_LOCATION = ['headers']
JWT_HEADER_NAME = 'Authorization'
JWT_HEADER_TYPE = 'Bearer'

FAB_ADD_SECURITY_VIEWS = True
FAB_ADD_SECURITY_API = True

# ==================== CORS - Critical for iframe embedding ====================

def _parse_cors_origins(raw: str) -> list:
    """Parse comma-separated origins from env, dropping wildcards.

    A bare "*" leaks data: combined with credentialed CORS, the browser will not
    actually send credentials, but a wildcard origin still allowed unauthenticated
    iframe embedding from any site, which broke our project-scoping in pre-Phase 3.
    Reject "*" defensively here regardless of env input.
    """
    items = [o.strip() for o in (raw or "").split(",")]
    return [o for o in items if o and o != "*"]


ENABLE_CORS = True
CORS_OPTIONS = {
    "supports_credentials": True,
    "allow_headers": [
        "Content-Type",
        "Authorization",
        "X-CSRFToken",
        "X-CSRF-Token",
        "Accept",
        "Origin",
    ],
    "expose_headers": ["X-CSRFToken", "X-CSRF-Token"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "origins": _parse_cors_origins(
        os.getenv(
            "SUPERSET_CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        )
    ),
}

# ==================== CSRF / WTF Configuration ====================

# Disable CSRF for API access (MCP server uses JWT Bearer token auth)
WTF_CSRF_ENABLED = False
WTF_CSRF_TIME_LIMIT = None
# Talisman / X-Frame-Options must allow the embed iframe. Talisman defaults to
# X-Frame-Options: SAMEORIGIN which blocks cross-origin iframe embedding from
# the frontend (different port). Either disable Talisman or configure it with
# frame-ancestors. We disable since CSP is enforced via CORS_OPTIONS instead.
TALISMAN_ENABLED = False
# Defensive: don't emit X-Frame-Options at all so iframe embedding from the
# allowed origins isn't blocked. Empty-string was tried first but browsers
# treat it as an invalid directive and log a console warning on every page
# load — better to omit the header entirely.
HTTP_HEADERS: dict = {}
WTF_CSRF_EXEMPT_LIST = ["*"]

# ==================== Feature Flags ====================
# Merge with Superset's defaults so we don't accidentally disable flags the
# core needs. Direct assignment to ``FEATURE_FLAGS`` replaces the dict whole
# in some loader paths.

try:
    from superset.config import DEFAULT_FEATURE_FLAGS as _DEFAULT_FF
except Exception:
    _DEFAULT_FF = {}

FEATURE_FLAGS = {
    **_DEFAULT_FF,
    "ALERT_REPORTS": True,
    "ENABLE_EXPLORE_DRAG_AND_DROP": True,
    "DISABLE_DATABASE_CONNECTION": False,
    # EMBEDDED_SUPERSET enables /embedded/<uuid> + Guest Token API used by the
    # frontend's @superset-ui/embedded-sdk. Iframe is rendered without cookies
    # of the Superset domain — the guest token alone authorizes the request,
    # so a developer logged in as admin in another tab does NOT leak admin
    # editing privileges into the chart iframe.
    "EMBEDDED_SUPERSET": True,
}
# Allow unsafe database connections (required for SQLite local files)
PREVENT_UNSAFE_DB_CONNECTIONS = False
# Public role has zero perms — no one can view a chart by guessing the URL.
# Access is gated by a short-lived Guest Token issued only to authenticated
# users who own the project. The token assumes GUEST_ROLE_NAME below.
PUBLIC_ROLE_LIKE = None
# Role that Guest Tokens assume. Gamma is read-only — view + download but no
# edit. Combined with the token's ``resources`` field (which restricts which
# dashboard the token may render), this gives users view-only access without
# inheriting any browser session privileges.
GUEST_ROLE_NAME = os.getenv("SUPERSET_GUEST_ROLE_NAME", "Gamma")
GUEST_TOKEN_JWT_EXP_SECONDS = int(os.getenv("SUPERSET_GUEST_TOKEN_TTL", "300"))
ALERT_REPORTS_NOTIFICATION_DRY_RUN = True

# Flask-Limiter off — Superset's default 50/s on guest_token locks the app
# out under any storm (multiple chart embeds reloading, dev hot-reload,
# embed-sdk timer overlap). The frontend talks only to authenticated users
# of this instance, so endpoint-level throttling adds noise without value.
RATELIMIT_ENABLED = False

SQLLAB_CTAS_NO_LIMIT = True
SQLLAB_TIMEOUT = int(os.getenv("SQLLAB_TIMEOUT", "300"))

log_level_text = os.getenv("SUPERSET_LOG_LEVEL", "INFO")
LOG_LEVEL = getattr(logging, log_level_text.upper(), logging.INFO)


# ==================== JWT → g.user workaround ====================
# Superset 4.x bug: when auth is via Authorization: Bearer <jwt>, g.user is never
# populated from the JWT identity. `security_manager.can_access()` reads `g.user`
# (Flask-Login style) and sees AnonymousUser, so base filters like DatabaseFilter
# return 0 results even for admin — while POST still works because it only checks
# JWT-decoded permissions. Root cause is that FAB's cookie-based login_manager
# sets g.user, but Flask-JWT-Extended does not.
#
# This hook runs before every request: if a valid Bearer token is present, load
# the User model by JWT subject and attach it to g.user so the rest of Superset's
# security layer sees the right user.
def FLASK_APP_MUTATOR(app):  # noqa: N802 — name required by Superset
    from flask import g, request
    from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

    @app.before_request
    def _attach_jwt_user_to_g() -> None:  # type: ignore[misc]
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return
        try:
            verify_jwt_in_request(optional=True)
            user_id = get_jwt_identity()
            if not user_id:
                return
            # Lazy imports — app context is active here, so these are safe
            from superset import db, security_manager
            user = db.session.get(security_manager.user_model, int(user_id))
            if user is not None:
                g.user = user
        except Exception:
            # Never block a request on our behalf; worst case FAB sees anonymous.
            pass
