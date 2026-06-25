"""Workflow helpers: DB operations + SQL verification (no LLM here).

- DB ops via the adapter in the ContextVar (get_db()): full_schema, table_names, run, explain.
- SQL verification (sqlglot AST + EXPLAIN): classify_access, is_read_only,
  verify_with_explain, verify_for_mutation. Kept here (not a separate module) because it's pure
  DB/SQL infrastructure with no LLM — the LLM-driven SQL generation lives in sql_gen.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import sqlglot
from sqlglot import exp

from app.agent.adapters.base import QueryResult, split_statements
from app.agent.context import get_db


def engine_name() -> str:
    return get_db().engine


async def full_schema() -> dict[str, list]:
    """Full schema {table: [Column]} of the project DB, in ONE query."""
    db = get_db()
    out: dict[str, list] = {}
    if db.primary is not None:
        out.update(await db.primary.get_schema())
    return out


async def table_names() -> list[str]:
    """Table names only — derived from the bulk schema (no separate list_tables round-trip)."""
    return list((await full_schema()).keys())


async def run(sql: str) -> QueryResult:
    db = get_db()
    adapter = db.primary
    if adapter is None:
        raise RuntimeError("No database connected")
    return await adapter.execute(sql)


async def explain(sql: str) -> str:
    db = get_db()
    adapter = db.primary
    if adapter is None:
        raise RuntimeError("No database connected")
    return await adapter.explain(sql)


def clean_db_error(raw: str) -> str:
    """Strip the SQLAlchemy/driver wrapper from a DB error, keeping the human-readable reason. e.g.
    '(sqlite3.OperationalError) near "x": syntax error\\n[SQL: ...]' → 'near "x": syntax error'.
    Shared by every workflow so a failed run surfaces the DB's reason, not the raw driver dump."""
    s = (raw or "").strip().splitlines()[0] if raw else ""
    s = re.sub(r"^\([^)]*\)\s*", "", s).strip()
    return s or "unknown database error"


# --- SQL verification: AST classification (sqlglot) + EXPLAIN -----------------------
# classify_access: parse + WALK THE WHOLE TREE → read_only / edit_data / invalid, with a finer
#                  DQL/DML/DDL kind. verify_with_explain: EXPLAIN via the adapter for semantic errors.

_DIALECT = {"sqlite": "sqlite", "postgresql": "postgres"}


def _dialect(engine: str) -> str:
    return _DIALECT.get(engine, "")


# How a SQL string accesses the DB. `access` is the coarse decision; `kind` is the finer
# operation class (the write path needs DML vs DDL to decide whether EXPLAIN is possible).
SqlAccess = Literal["read_only", "edit_data", "invalid"]
SqlKind = Literal["DQL", "DML", "DDL", "INVALID"]

_DDL_NODES = (exp.Create, exp.Drop, exp.Alter, exp.TruncateTable)
_DML_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge)


@dataclass
class AccessInfo:
    access: SqlAccess
    kind: SqlKind


def classify_access(sql: str, engine: str = "sqlite") -> AccessInfo:
    """Check the SQL and classify it by WALKING THE WHOLE AST (not just the root node).

    Returns (access, kind):
    - access 'invalid' / kind 'INVALID' → empty, a syntax error (sqlglot can't parse), or an
      opaque statement sqlglot models as `Command` (e.g. VACUUM) where read/edit can't be told.
    - access 'edit_data' → any write node anywhere in the tree (so a write hidden in a CTE/subquery
      still counts); kind 'DDL' if any CREATE/DROP/ALTER/TRUNCATE, else 'DML'.
    - access 'read_only' / kind 'DQL' → otherwise.

    Note: sqlglot is lenient, so this only catches GROSS syntax errors (unbalanced parens, missing
    clauses). A typo like `SELEC * FORM t` may still parse; full validity needs EXPLAIN.
    """
    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return AccessInfo("invalid", "INVALID")
    try:
        nodes = [s for s in sqlglot.parse(raw, read=_dialect(engine) or None) if s is not None]
    except Exception:  # noqa: BLE001 — parse failure = syntax error
        return AccessInfo("invalid", "INVALID")
    if not nodes:
        return AccessInfo("invalid", "INVALID")

    has_ddl = has_dml = False
    for node in nodes:
        if isinstance(node, exp.Command):  # sqlglot couldn't fully parse it → can't classify
            return AccessInfo("invalid", "INVALID")
        if next(node.find_all(*_DDL_NODES), None) is not None:
            has_ddl = True
        elif next(node.find_all(*_DML_NODES), None) is not None:
            has_dml = True
    if has_ddl:
        return AccessInfo("edit_data", "DDL")
    if has_dml:
        return AccessInfo("edit_data", "DML")
    return AccessInfo("read_only", "DQL")


def is_read_only(sql: str, engine: str = "sqlite") -> bool:
    """Convenience bool wrapper over classify_access (True only for read-only SQL)."""
    return classify_access(sql, engine).access == "read_only"


def is_bare_create_table(sql: str, engine: str = "sqlite") -> bool:
    """True if the batch CREATEs a new TABLE WITHOUT dropping or renaming one — a plain table
    creation that belongs on the create-table flow, not the mutation path. The recreate-for-ALTER
    pattern (the only legit reason a mutation creates a table) always RENAMEs the original away and
    DROPs it, so the presence of any DROP/ALTER means it's a recreate, not a bare create."""
    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return False
    try:
        nodes = [s for s in sqlglot.parse(raw, read=_dialect(engine) or None) if s is not None]
    except Exception:  # noqa: BLE001
        return False
    has_create_table = has_drop = has_alter = False
    for node in nodes:
        for c in node.find_all(exp.Create):
            if str(c.args.get("kind") or "").upper() == "TABLE":
                has_create_table = True
        if next(node.find_all(exp.Drop), None) is not None:
            has_drop = True
        if next(node.find_all(exp.Alter), None) is not None:
            has_alter = True
    return has_create_table and not has_drop and not has_alter


async def verify_with_explain(sql: str) -> tuple[bool, str]:
    """EXPLAIN via the adapter. (ok, error)."""
    try:
        await explain(sql)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


async def verify_for_mutation(sql: str, engine: str) -> tuple[bool, str, str]:
    """Return (ok, error, kind) for the mutation path: AST classification + EXPLAIN (skipped for DDL).

    - DQL (read) is rejected — the mutation path must not accept read-only queries.
    - DDL (ALTER/CREATE/DROP) cannot be EXPLAINed in either SQLite or PostgreSQL, so EXPLAIN is
      skipped and the static classification is trusted.
    - DML (INSERT/UPDATE/DELETE) runs EXPLAIN as a semantic check — per statement, so a
      multi-statement batch is validated one statement at a time.
    """
    info = classify_access(sql, engine)
    if info.kind == "INVALID":
        return False, "Invalid or unparseable SQL.", "INVALID"
    if info.kind == "DQL":
        return False, "Read-only SELECT is not allowed on the mutation path.", "DQL"
    if info.kind == "DDL":
        return True, "", "DDL"
    for stmt in split_statements(sql, engine):  # EXPLAIN each DML statement separately
        ok, err = await verify_with_explain(stmt)
        if not ok:
            return False, err, "DML"
    return True, "", "DML"
