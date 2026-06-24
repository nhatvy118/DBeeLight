"""resolve_scope — the SINGLE place that maps a table to its description scope key.

Used by BOTH the writer (create_table capture) and the reader (schema discovery enrich),
so the key is always computed identically and the two sides never drift.

  primary DB table  → ('project', project_id)
                      project_id is the real project id, or 'user:<user_id>' for the
                      per-user external connection (see _authorize in chat/service).
  session/file table → None for now (file scope is deferred; see Phase 5).
"""
from __future__ import annotations

from app.agent.context import get_ctx


def resolve_scope(table_name: str) -> tuple[str, str] | None:
    """Return (scope_type, scope_id) for a table, or None if it has no description scope
    (file/session tables for now, or no usable primary)."""
    ctx = get_ctx()
    db = ctx.db
    # Scope is project-level, so it depends only on which DB the request is on, not the specific
    # table (primary and session are mutually exclusive per request, see chat._build_ctx):
    #   session/file turn → primary is None → no project scope (file scope deferred).
    #   primary turn      → every table belongs to the project.
    if db.primary is None:
        return None
    if not ctx.project_id:
        return None
    return ("project", ctx.project_id)
