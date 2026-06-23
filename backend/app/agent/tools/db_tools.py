"""In-process database tools. The adapter comes from the ContextVar (get_db()), not a parameter.

The LLM only produces business args (query, table_name, ...); the connection is injected implicitly.
"""
from __future__ import annotations

import re

from app.agent.adapters.base import QueryResult
from app.agent.graph.dbtools import full_schema
from app.agent.graph.schema_context import enrich_schema_text, render_schema
from app.agent.tools.registry import tool

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


# Names of the DB tools (attached to the DatabaseAgent's InProcessBackend).
# db_general is a STRUCTURE/MEANING agent only — reading row data is the db_readonly route's
# job (the SELECT workflow), so no select_data/execute_query/explain_sql here.
DB_TOOL_NAMES = [
    "get_schema",
    "describe_schema",
]
