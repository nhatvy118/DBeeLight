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
    "origins": [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "*",  # Allow all for testing; restrict in production
    ],
}

# ==================== CSRF / WTF Configuration ====================

# Disable CSRF for API access (MCP server uses JWT Bearer token auth)
WTF_CSRF_ENABLED = False
WTF_CSRF_TIME_LIMIT = None
TALISMAN_ENABLED = False
WTF_CSRF_EXEMPT_LIST = ["*"]

# ==================== Feature Flags ====================

FEATURE_FLAGS = {
    "ALERT_REPORTS": True,
    "ENABLE_EXPLORE_DRAG_AND_DROP": True,
    "DISABLE_DATABASE_CONNECTION": False,
}
# Allow unsafe database connections (required for SQLite local files)
PREVENT_UNSAFE_DB_CONNECTIONS = False
PUBLIC_ROLE_LIKE = "Gamma"
ALERT_REPORTS_NOTIFICATION_DRY_RUN = True

SQLLAB_CTAS_NO_LIMIT = True
SQLLAB_TIMEOUT = int(os.getenv("SQLLAB_TIMEOUT", "300"))

log_level_text = os.getenv("SUPERSET_LOG_LEVEL", "INFO")
LOG_LEVEL = getattr(logging, log_level_text.upper(), logging.INFO)
