"""Build the schema text fed to the SQL-generating LLM: the LIVE structure (tables,
columns, types — always the source of truth) enriched with the semantic data dictionary
(table/column descriptions + enum values) so the model understands what columns mean.

Descriptions are best-effort: a column without one still appears (from the live schema),
just without the "— meaning" suffix. External/undescribed tables degrade gracefully.
"""
from __future__ import annotations

import logging

from app.agent.context import get_db
from app.features.metadata import repository as metadata_repo
from app.features.metadata.scope import resolve_scope
from app.features.projects import repository as proj_repo

logger = logging.getLogger("agent.graph.schema_context")


async def enrich_schema_text(tables: list[str], limit: int = 30) -> str:
    """Return a human/LLM-readable schema for `tables`, enriched with descriptions."""
    tables = [t for t in tables][:limit]
    if not tables:
        return ""
    db = get_db()

    # Live structure (authoritative).
    cols_by_table: dict[str, list] = {}
    for t in tables:
        adapter = db.adapter_for_table(t)
        cols_by_table[t] = (await adapter.describe_table(t)) if adapter else []

    # Descriptions: all primary tables share one project scope; file/session tables → no scope.
    scope = None
    scoped: list[str] = []
    for t in tables:
        sc = resolve_scope(t)
        if sc:
            scope, _ = sc, scoped.append(t)

    tbl_desc: dict[str, str] = {}
    col_desc: dict[tuple[str, str], dict] = {}
    db_desc: str | None = None
    if scope and scoped:
        try:
            tbl_desc, col_desc = await metadata_repo.get_for_scope(scope[0], scope[1], scoped)
            if scope[0] == "project" and not str(scope[1]).startswith("user:"):
                db_desc = await proj_repo.get_description_any(scope[1])
        except Exception as e:  # noqa: BLE001 — enrichment must never break query generation
            logger.warning("schema enrichment lookup failed: %s", e)

    lines: list[str] = []
    if db_desc:
        lines.append(f"[Database] {db_desc}")
    for t in tables:
        td = tbl_desc.get(t.lower())
        lines.append(f"- {t}" + (f" — {td}" if td else ""))
        for c in cols_by_table[t]:
            m = col_desc.get((t.lower(), str(c.name).lower()))
            d = f" — {m['desc']}" if m else ""
            e = f" [allowed values: {m['enum']}]" if m and m.get("enum") else ""
            lines.append(f"    {c.name} {c.type}{d}{e}")
    return "\n".join(lines)
