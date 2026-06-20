"""Workflow helpers: DB operations via the adapter in the ContextVar (get_db()).

Replaces the old ``_call_tool(agent, ...)`` — no more MCP session.
"""
from __future__ import annotations

from app.agent.adapters.base import QueryResult
from app.agent.context import get_db


def engine_name() -> str:
    return get_db().engine


async def list_tables() -> list[str]:
    db = get_db()
    out: list[str] = []
    if db.primary is not None:
        out += await db.primary.list_tables()
    if db.session is not None:
        out += await db.session.list_tables()
    return out


async def run(sql: str) -> QueryResult:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        raise RuntimeError("No database connected")
    return await adapter.execute(sql)


async def explain(sql: str) -> str:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        raise RuntimeError("No database connected")
    return await adapter.explain(sql)


def md_table(res: QueryResult, limit: int = 50) -> str:
    if not res.columns:
        return f"_OK ({res.rowcount} rows)._"
    head = "| " + " | ".join(res.columns) + " |"
    sep = "| " + " | ".join("---" for _ in res.columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in res.rows[:limit]]
    return "\n".join([head, sep, *body])
