"""In-process database tools. The adapter comes from the ContextVar (get_db()), not a parameter.

The LLM only produces business args (query, table_name, ...); the connection is injected implicitly.
"""
from __future__ import annotations

from app.agent.adapters.base import QueryResult
from app.agent.graph.dbtools import clean_db_error, engine_name, full_schema, is_read_only, run
from app.agent.graph.schema_context import enrich_schema_text, render_schema
from app.agent.tools.registry import tool


def _result_to_text(res: QueryResult, limit: int = 100) -> str:
    """Render a query result as a compact Markdown table for the LLM to read and reason over."""
    if not res.columns:
        return f"OK ({res.rowcount} rows affected)."
    head = "| " + " | ".join(res.columns) + " |"
    sep = "| " + " | ".join("---" for _ in res.columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in res.rows[:limit]]
    extra = "" if len(res.rows) <= limit else f"\n…{len(res.rows) - limit} more rows (showing {limit})."
    return "\n".join([head, sep, *body]) + extra


@tool(
    description=(
        "Get the schema of the connected database in one call: every table with its columns, "
        "data types, nullability, primary keys, foreign keys (shown as → target), and defaults. "
        "This is the single way to inspect structure before writing SQL."
    ),
    parameters={"type": "object", "properties": {}},
)
async def get_schema() -> str:
    cols_by_table = await full_schema()
    if not cols_by_table:
        return "No database connected."
    return render_schema(cols_by_table)


@tool(
    description=(
        "Describe the database in BUSINESS terms — the data dictionary. Returns every table and "
        "column with its data type, keys and relationships PLUS the saved human description / "
        "meaning and the allowed values (enums) where they exist. Use this — not get_schema — for "
        "questions about what the database/table/column MEANS, how many columns a table has, what "
        "a table is for, or to explain the schema in natural language. get_schema gives raw "
        "structure only; this adds the business meaning."
    ),
    parameters={"type": "object", "properties": {}},
)
async def describe_schema() -> str:
    text = await enrich_schema_text(mode="read")
    return text or "No database connected."


@tool(
    description=(
        "Run a READ-ONLY SELECT and get the rows back, to ANALYZE the data. Use this to answer "
        "analytical questions ('why did revenue drop', 'what's driving X', trends, comparisons, "
        "root-cause) by running SEVERAL queries and reasoning over the results. Read-only only: "
        "SELECT / CTE / aggregate queries — never INSERT/UPDATE/DELETE or any DDL."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A read-only SELECT query"}},
        "required": ["query"],
    },
)
async def execute_query(query: str) -> str:
    if not is_read_only(query, engine_name()):
        return "Rejected: only read-only SELECT queries are allowed here (no INSERT/UPDATE/DELETE/DDL)."
    try:
        res = await run(query)
    except Exception as e:  # noqa: BLE001
        return f"Query error: {clean_db_error(str(e))}"
    return _result_to_text(res)


# Names of the DB tools (attached to the DatabaseAgent's InProcessBackend).
# db_general is the agentic READ agent: inspect schema/meaning (get_schema / describe_schema) and
# run read-only queries to analyze (execute_query). It never mutates — writes go to db_mutation.
DB_TOOL_NAMES = [
    "get_schema",
    "describe_schema",
    "execute_query",
]
