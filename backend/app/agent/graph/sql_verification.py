"""Tiered SQL verification (sqlglot static + EXPLAIN), and blocking writes on the read-only path.

- tier1_static: parse + classify (DQL / DML / DDL), catch syntax errors, block multi-statement.
- require_dql_only: used by the ReadOnly workflow — SELECT only.
- tier2_explain: EXPLAIN via the adapter to catch semantic errors before running.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import sqlglot
from sqlglot import exp

from app.agent.graph import dbtools

logger = logging.getLogger("agent.graph.sqlverify")

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


def _classify(node: exp.Expression) -> Kind:
    if isinstance(node, (exp.Select, exp.Union, exp.With)):
        return "DQL"
    if isinstance(node, (exp.Insert, exp.Update, exp.Delete)):
        return "DML"
    if isinstance(node, (exp.Create, exp.Drop, exp.Alter, exp.TruncateTable)):
        return "DDL"
    return "OTHER"


def require_dql_only(sql: str, engine: str = "sqlite") -> str | None:
    """Return an error message if the SQL is NOT a SELECT (blocks sneaky writes in readonly). None = OK."""
    t1 = tier1_static(sql, engine)
    if not t1.ok:
        return t1.error
    if t1.kind != "DQL":
        return f"The read-only path only allows SELECT (got {t1.kind})."
    return None


async def tier2_explain(sql: str) -> tuple[bool, str]:
    """EXPLAIN qua adapter. (ok, error)."""
    try:
        await dbtools.explain(sql)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


async def verify_for_mutation(sql: str, engine: str) -> tuple[bool, str, str]:
    """Return (ok, error, kind) for the mutation path: tier1 + EXPLAIN."""
    t1 = tier1_static(sql, engine)
    if not t1.ok:
        return False, t1.error or "Invalid SQL", "INVALID"
    ok, err = await tier2_explain(sql)
    return (ok, err, t1.kind)
