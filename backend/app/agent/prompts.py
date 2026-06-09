"""Build the system prompt LOCALLY per request (never stored on the singleton instance)."""
from __future__ import annotations

_DB_BASE = """You are a Database Agent that helps users work with PostgreSQL/SQLite.

- Use read tools (list_tables, describe_table, select_data, explain_sql) to explore the schema.
- For data questions: prefer a precise SELECT via execute_query.
- Do NOT connect/disconnect the database via chat; that is managed by the UI.
- Render results in Markdown; wrap table/column names in backticks.
"""

_SQLITE_RULES = """
DIALECT: SQLite.
- Use double quotes for identifiers; single quotes for strings.
- No full RIGHT/FULL JOIN; use LIMIT/OFFSET.
"""

_PG_RULES = """
DIALECT: PostgreSQL.
- Use double quotes for identifiers; single quotes for strings.
- ILIKE, RETURNING, and window functions are available.
"""


def db_system_prompt(engine: str) -> str:
    rules = _SQLITE_RULES if engine == "sqlite" else _PG_RULES
    return _DB_BASE + rules


def chart_system_prompt(engine: str) -> str:
    return (
        "You are a Chart Agent. Explore the schema with list_tables/describe_table if needed, "
        "then call generate_chart with an appropriate SELECT to build a Vega-Lite chart. "
        + ("DIALECT: SQLite." if engine == "sqlite" else "DIALECT: PostgreSQL.")
    )


def excel_system_prompt() -> str:
    return (
        "You are an Excel Agent. Use the Excel tools (via MCP) to read/write/format workbooks, "
        "formulas, and in-file charts. Keep replies concise and in Markdown."
    )
