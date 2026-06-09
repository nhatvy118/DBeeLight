"""In-process database tools. The adapter comes from the ContextVar (get_db()), not a parameter.

The LLM only produces business args (query, table_name, ...); the connection is injected implicitly.
"""
from __future__ import annotations

import re

from app.agent.adapters.base import QueryResult
from app.agent.context import get_db
from app.agent.tools.registry import tool

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _md_table(res: QueryResult, limit: int = 100) -> str:
    if not res.columns:
        return f"_OK ({res.rowcount} rows affected)._"
    head = "| " + " | ".join(res.columns) + " |"
    sep = "| " + " | ".join("---" for _ in res.columns) + " |"
    body = []
    for r in res.rows[:limit]:
        body.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    extra = "" if len(res.rows) <= limit else f"\n\n_…{len(res.rows) - limit} more rows._"
    return "\n".join([head, sep, *body]) + extra


def _safe_ident(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


@tool(
    description="List all tables in the connected database.",
    parameters={"type": "object", "properties": {}},
)
async def list_tables() -> str:
    db = get_db()
    out: list[str] = []
    if db.primary is not None:
        tables = await db.primary.list_tables()
        out.append("**Tables (project DB):** " + (", ".join(f"`{t}`" for t in tables) or "(none)"))
    if db.session is not None:
        tables = await db.session.list_tables()
        out.append("**Tables (uploaded files):** " + (", ".join(f"`{t}`" for t in tables) or "(none)"))
    return "\n\n".join(out) or "No database connected."


@tool(
    description="Describe the columns and data types of a table.",
    parameters={
        "type": "object",
        "properties": {"table_name": {"type": "string"}},
        "required": ["table_name"],
    },
)
async def describe_table(table_name: str) -> str:
    db = get_db()
    adapter = db.adapter_for_table(table_name)
    if adapter is None:
        return "No database connected."
    cols = await adapter.describe_table(_safe_ident(table_name))
    if not cols:
        return f"Table `{table_name}` not found."
    lines = ["| Column | Type | Nullable | PK |", "| --- | --- | --- | --- |"]
    for c in cols:
        lines.append(f"| {c.name} | {c.type} | {'YES' if c.nullable else 'NO'} | {'✓' if c.pk else ''} |")
    return "\n".join(lines)


@tool(
    description="Read rows from a table with optional filter/limit (read-only).",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "columns": {"type": "string", "description": "Column list, default '*'"},
            "where_clause": {"type": "string", "description": "WHERE condition, without the WHERE keyword"},
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["table_name"],
    },
)
async def select_data(
    table_name: str, columns: str = "*", where_clause: str | None = None, limit: int = 100
) -> str:
    db = get_db()
    adapter = db.adapter_for_table(table_name)
    if adapter is None:
        return "No database connected."
    sql = f'SELECT {columns} FROM "{_safe_ident(table_name)}"'
    if where_clause:
        sql += f" WHERE {where_clause}"
    sql += f" LIMIT {int(limit)}"
    res = await adapter.execute(sql)
    return _md_table(res, limit)


@tool(
    description="Run a SQL statement (read-only SELECT). Mutations must go through the approval flow.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)
async def execute_query(query: str) -> str:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return "No database connected."
    res = await adapter.execute(query)
    return _md_table(res)


@tool(
    description="Current connection info (sensitive details redacted).",
    parameters={"type": "object", "properties": {}},
)
async def get_connection_info() -> str:
    # REDACT: never return the DSN/host/password to the LLM.
    db = get_db()
    if db.any_adapter is None:
        return "No database connected."
    return f"Connected. Engine: {db.engine}."


@tool(
    description="Validate syntax and EXPLAIN a SQL statement without running it.",
    parameters={
        "type": "object",
        "properties": {"sql": {"type": "string"}},
        "required": ["sql"],
    },
)
async def explain_sql(sql: str) -> str:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return "No database connected."
    try:
        plan = await adapter.explain(sql)
        return f"OK.\n```\n{plan}\n```"
    except Exception as e:  # noqa: BLE001
        return f"Invalid SQL: {e}"


# Names of the DB tools (attached to the DatabaseAgent's InProcessBackend)
DB_TOOL_NAMES = [
    "list_tables",
    "describe_table",
    "select_data",
    "execute_query",
    "get_connection_info",
    "explain_sql",
]
