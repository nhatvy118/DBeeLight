"""Data-access for the semantic data dictionary (`descriptions` table).

Stores plain-language meaning of tables/columns so the SQL agent writes accurate queries.
Names are normalized to lowercase on write AND read so the join with live schema is reliable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db import get_pool

logger = logging.getLogger("metadata.repo")


async def upsert_descriptions(scope_type: str, scope_id: str, rows: list[dict[str, Any]]) -> None:
    """Insert/overwrite descriptions for a scope.

    rows: [{"table": str, "column": str | None, "description": str, "enum": list | None}, ...]
    column=None → table-level description.
    """
    if not rows:
        return
    args = []
    for r in rows:
        table = str(r.get("table") or "").strip().lower()
        if not table or not r.get("description"):
            continue
        column = r.get("column")
        column = str(column).strip().lower() if column else None
        enum = r.get("enum")
        args.append((scope_type, scope_id, table, column, r["description"],
                     json.dumps(enum) if enum is not None else None))
    if not args:
        return
    await get_pool().executemany(
        """
        INSERT INTO descriptions (scope_type, scope_id, table_name, column_name, description, enum_values)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        ON CONFLICT (scope_type, scope_id, table_name, COALESCE(column_name, ''))
        DO UPDATE SET description = EXCLUDED.description,
                      enum_values = EXCLUDED.enum_values,
                      updated_at  = now()
        """,
        args,
    )


async def get_for_scope(
    scope_type: str, scope_id: str, table_names: list[str]
) -> tuple[dict[str, str], dict[tuple[str, str], dict]]:
    """Return (table_desc, column_desc) for the given tables in one query.

    table_desc:  {table_lower: description}
    column_desc: {(table_lower, column_lower): {"desc": str, "enum": list | None}}
    """
    if not table_names:
        return {}, {}
    rows = await get_pool().fetch(
        """
        SELECT table_name, column_name, description, enum_values
        FROM descriptions
        WHERE scope_type = $1 AND scope_id = $2 AND table_name = ANY($3::text[])
        """,
        scope_type, scope_id, [t.lower() for t in table_names],
    )
    tbl: dict[str, str] = {}
    col: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r["column_name"] is None:
            tbl[r["table_name"]] = r["description"]
        else:
            enum = r["enum_values"]
            if isinstance(enum, str):
                enum = json.loads(enum)
            col[(r["table_name"], r["column_name"])] = {"desc": r["description"], "enum": enum}
    return tbl, col


async def delete_for_scope(scope_type: str, scope_id: str) -> None:
    """Drop all descriptions for a scope. Called when a project's DB is disconnected (the
    project's scope id is REUSED, so stale descriptions must not leak to the next connected
    DB) or when a project is deleted."""
    await get_pool().execute(
        "DELETE FROM descriptions WHERE scope_type = $1 AND scope_id = $2",
        scope_type, scope_id,
    )
