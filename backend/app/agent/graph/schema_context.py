"""Render the connected DB's schema as text for an LLM.

Two layers:
- `render_schema()` — pure formatter over the structured schema dict (dbtools.full_schema).
  DDL-ish, compact. PK / NOT NULL / FK (→) are always shown; default / UNIQUE are write-only
  metadata and dropped in `lean` mode (the read path doesn't need them).
- `enrich_schema_text()` — pulls the live structure + the semantic dictionary (table/column
  descriptions + user-entered enum values) and renders them together.

Descriptions are best-effort: a column without one still appears (from the live schema), just
without the "— meaning"/"[enum]" suffix. External/undescribed tables degrade gracefully.
"""
from __future__ import annotations

import logging

from app.agent.adapters.base import Column
from app.agent.graph import dbtools
from app.features.metadata import repository as metadata_repo
from app.features.metadata.scope import resolve_scope
from app.features.projects import repository as proj_repo

logger = logging.getLogger("agent.graph.schema_context")


def _column_segment(c: Column, meta: dict | None, *, lean: bool) -> str:
    seg = f"{c.name} {c.type}"
    if c.pk:
        seg += " PK"
    elif not c.nullable:
        seg += " NOT NULL"
    if c.references:
        seg += f" → {c.references}"           # FK target (JOIN hint) — always useful
    if not lean and c.unique:
        seg += " UNIQUE"                       # write-only hint (UPSERT / row identity)
    if not lean and c.default is not None:
        seg += f" DEFAULT {c.default}"         # write-only hint (column is omittable on INSERT)
    if meta and meta.get("enum"):
        seg += f" [{meta['enum']}]"            # user-entered allowed values
    if meta and meta.get("desc"):
        seg += f" — {meta['desc']}"            # user-entered meaning
    return seg


def render_schema(
    cols_by_table: dict[str, list[Column]],
    *,
    db_desc: str | None = None,
    tbl_desc: dict[str, str] | None = None,
    col_desc: dict[tuple[str, str], dict] | None = None,
    lean: bool = False,
    limit: int = 30,
) -> str:
    """Format the structured schema into DDL-ish text: `table — desc(col TYPE PK …, …)`."""
    tbl_desc = tbl_desc or {}
    col_desc = col_desc or {}
    lines: list[str] = []
    if db_desc:
        lines.append(f"[Database] {db_desc}")
    for t in list(cols_by_table.keys())[:limit]:
        segs = [
            _column_segment(c, col_desc.get((t.lower(), str(c.name).lower())), lean=lean)
            for c in cols_by_table[t]
        ]
        td = tbl_desc.get(t.lower())
        header = t + (f" — {td}" if td else "")
        lines.append(f"{header}(" + ", ".join(segs) + ")")
    return "\n".join(lines)


async def enrich_schema_text(*, mode: str = "write", limit: int = 30) -> str:
    """Live structure (dbtools.full_schema, bulk) + semantic dictionary, rendered as text.
    `mode="read"` drops write-only metadata (default/UNIQUE) the SELECT path doesn't need."""
    cols_by_table = await dbtools.full_schema()  # {table: [Column]} — bulk, no N+1
    if not cols_by_table:
        return ""
    tables = list(cols_by_table.keys())[:limit]

    # Descriptions: all primary tables share one project scope; file/session tables → no scope.
    scope = None
    scoped: list[str] = []
    for t in tables:
        sc = resolve_scope(t)
        if sc:
            scope = sc           # shared by every scoped (project) table
            scoped.append(t)     # only these get a description lookup

    tbl_desc: dict[str, str] = {}
    col_desc: dict[tuple[str, str], dict] = {}
    db_desc: str | None = None
    if scope and scoped:
        try:
            tbl_desc, col_desc = await metadata_repo.get_for_scope(scope[0], scope[1], scoped)
            db_desc = await proj_repo.get_description_any(scope[1])  # scope_id is always a project id
        except Exception as e:  # noqa: BLE001 — enrichment must never break query generation
            logger.warning("schema enrichment lookup failed: %s", e)

    return render_schema(cols_by_table, db_desc=db_desc, tbl_desc=tbl_desc, col_desc=col_desc,
                         lean=(mode == "read"), limit=limit)
