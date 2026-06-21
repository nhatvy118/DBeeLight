"""Workflow helpers: DB operations + SQL verification (no LLM here).

- DB ops via the adapter in the ContextVar (get_db()): full_schema, table_names, run, explain, md_table.
- Tiered SQL verification (sqlglot static + EXPLAIN): tier1_static, require_dql_only,
  tier2_explain, verify_for_mutation. Kept here (not a separate module) because it's pure
  DB/SQL infrastructure with no LLM — the LLM-driven SQL generation lives in sql_gen.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import sqlglot
from sqlglot import exp

from app.agent.adapters.base import QueryResult
from app.agent.context import get_db


def engine_name() -> str:
    return get_db().engine


async def full_schema() -> dict[str, list]:
    """Full schema {table: [Column]} across primary + session DBs, each in ONE query."""
    db = get_db()
    out: dict[str, list] = {}
    if db.primary is not None:
        out.update(await db.primary.get_schema())
    if db.session is not None:
        out.update(await db.session.get_schema())
    return out


async def table_names() -> list[str]:
    """Table names only — derived from the bulk schema (no separate list_tables round-trip)."""
    return list((await full_schema()).keys())


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


def clean_db_error(raw: str) -> str:
    """Strip the SQLAlchemy/driver wrapper from a DB error, keeping the human-readable reason. e.g.
    '(sqlite3.OperationalError) near "x": syntax error\\n[SQL: ...]' → 'near "x": syntax error'.
    Shared by every workflow so a failed run surfaces the DB's reason, not the raw driver dump."""
    s = (raw or "").strip().splitlines()[0] if raw else ""
    s = re.sub(r"^\([^)]*\)\s*", "", s).strip()
    return s or "unknown database error"


# --- Tiered SQL verification (static sqlglot + EXPLAIN) ----------------------------
# tier1_static: parse + classify (DQL/DML/DDL), catch syntax errors, block multi-statement.
# tier2_explain: EXPLAIN via the adapter to catch semantic errors before running.
Kind = Literal["DQL", "DML", "DDL", "OTHER", "INVALID"]

_DIALECT = {"sqlite": "sqlite", "postgresql": "postgres"}


def _dialect(engine: str) -> str:
    return _DIALECT.get(engine, "")


@dataclass
class Tier1Result:
    ok: bool
    kind: Kind
    error: str | None = None
    normalized: str | None = None


def _classify(node: Any) -> Kind:
    if isinstance(node, (exp.Select, exp.Union, exp.With)):
        return "DQL"
    if isinstance(node, (exp.Insert, exp.Update, exp.Delete)):
        return "DML"
    if isinstance(node, (exp.Create, exp.Drop, exp.Alter, exp.TruncateTable)):
        return "DDL"
    return "OTHER"


def tier1_static(sql: str, engine: str = "sqlite") -> Tier1Result:
    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return Tier1Result(ok=False, kind="INVALID", error="Empty SQL")
    try:
        stmts = sqlglot.parse(raw, read=_dialect(engine) or None)
    except Exception as e:  # noqa: BLE001
        return Tier1Result(ok=False, kind="INVALID", error=f"Syntax error: {e}")
    stmts = [s for s in stmts if s is not None]
    if len(stmts) != 1:
        return Tier1Result(ok=False, kind="INVALID", error="Only a single statement is allowed")
    node = stmts[0]
    kind = _classify(node)
    return Tier1Result(ok=True, kind=kind, normalized=node.sql(dialect=_dialect(engine) or None))


def require_dql_only(sql: str, engine: str = "sqlite") -> str | None:
    """Return an error message if the SQL is NOT a SELECT (blocks sneaky writes in readonly). None = OK."""
    t1 = tier1_static(sql, engine)
    if not t1.ok:
        return t1.error
    if t1.kind != "DQL":
        return f"The read-only path only allows SELECT (got {t1.kind})."
    return None


async def tier2_explain(sql: str) -> tuple[bool, str]:
    """EXPLAIN via the adapter. (ok, error)."""
    try:
        await explain(sql)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


async def verify_for_mutation(sql: str, engine: str) -> tuple[bool, str, str]:
    """Return (ok, error, kind) for the mutation path: tier1 + EXPLAIN (skipped for DDL).

    - DQL (SELECT) is rejected — mutation path must not accept read-only queries.
    - DDL (ALTER/CREATE/DROP) cannot be EXPLAINed in either SQLite or PostgreSQL, so tier2 is
      skipped and tier1 static analysis is trusted alone.
    - DML (INSERT/UPDATE/DELETE) runs tier2 EXPLAIN as a semantic check.
    """
    t1 = tier1_static(sql, engine)
    if not t1.ok:
        return False, t1.error or "Invalid SQL", "INVALID"
    if t1.kind == "DQL":
        return False, "Read-only SELECT is not allowed on the mutation path.", "DQL"
    if t1.kind == "DDL":
        return True, "", t1.kind
    ok, err = await tier2_explain(sql)
    return (ok, err, t1.kind)
