# Multi-stage build for api-server.
#
# Build context MUST be the monorepo root (not api-server/), because:
#   - api-server depends on `mcp-client` via [tool.uv.sources] path = "../mcp-client"
#   - MCP servers under mcp-client/servers/* each have their own pyproject.toml
#     and need their own .venv at runtime (base_agent.py spawns each as a
#     subprocess and looks for sibling .venv/bin/python).
#
# Build from repo root:
#   docker build -f api-server/Dockerfile -t dbeelight-api .

# ============ Builder ============
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

# Pin uv version — keep in sync with developer env (`uv --version`) when bumping.
COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy mcp-client first so api-server's editable dep resolves to /app/mcp-client.
COPY mcp-client/ ./mcp-client/

# Each MCP server runs as a stdio subprocess with its OWN venv (see
# mcp_agent/agents/base_agent.py). Provision them at build time so cold
# spawn is fast at runtime.
RUN set -eux; \
    for d in mcp-client/servers/*/; do \
        if [ -f "$d/pyproject.toml" ]; then \
            echo "Syncing $d"; \
            (cd "$d" && (uv sync --frozen --no-dev || uv sync --no-dev)); \
        fi; \
    done

# Now sync api-server itself.
COPY api-server/pyproject.toml api-server/uv.lock api-server/README.md ./api-server/
COPY api-server/internal ./api-server/internal
COPY api-server/migrations_pg ./api-server/migrations_pg

RUN cd api-server && uv sync --frozen --no-dev

# ============ Runtime ============
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/api-server/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Runtime OS deps only — no compilers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r app \
    && useradd -r -g app -d /app -s /bin/bash app

WORKDIR /app

# Copy entire prepared tree (all venvs + source).
COPY --from=builder --chown=app:app /app /app

# Create writable dirs for runtime file IO (overridden by volumes in dev,
# replaced with S3 adapter in prod). These must match _internal_data_root()
# in internal/features/file/service.py — everything lives under internal/.
RUN mkdir -p /app/api-server/internal/file_handle \
             /app/api-server/internal/temp_dbs \
             /app/api-server/internal/databases \
    && chown -R app:app /app/api-server/internal/file_handle \
                        /app/api-server/internal/temp_dbs \
                        /app/api-server/internal/databases

USER app
WORKDIR /app/api-server

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5001/api/health || exit 1

# The api-server console script is provided by [project.scripts] in pyproject.toml.
CMD ["api-server"]
