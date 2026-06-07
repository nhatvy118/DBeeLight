"""4-tier SQL verification before showing SQL to the user.

Flow (same for SQLite project DB and PostgreSQL):

  Tier 1 — ``tier1_static_analyze``: sqlglot parse + classify + risk warnings (no hard blocks
  except empty/unparseable SQL). Warnings surface in the preview EXPLAIN summary.
  Tier 2 — ``tier2_explain_verify``: ``explain_sql`` once (DQL/DML: SELECT/UNION/…, INSERT, UPDATE, DELETE).
  Tier 3 — ``tier3_ddl_verify``: ``validate_sql`` → dry-run DDL + rollback (CREATE/ALTER/DROP).
  Tier 4 — Workflows: preview UI + human Execute (not in this module).

Engine differences (adapters only):
  - SQLite: ``EXPLAIN QUERY PLAN`` in ``explain_sql``; DDL rollback via BEGIN/ROLLBACK.
  - PostgreSQL: ``EXPLAIN`` in ``explain_sql``; DDL rollback via transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, List, Literal

import sqlglot
from sqlglot import exp

from mcp_agent.graph.database_utils import (
    describe_explain_plan_naturally,
    detect_db_type,
    effective_db_type_for_sql,
    is_sql_tool_error,
    strip_sql_fences,
)

logger = logging.getLogger(__name__)

VerifyTier = Literal["tier1", "tier2_explain", "tier3_ddl", "none"]

_LOG_SQL_MAX = 200


def _sql_log_snippet(sql: str, *, max_len: int = _LOG_SQL_MAX) -> str:
    one_line = " ".join((sql or "").split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 3] + "..."

# sqlglot root expression types (order matters in _classify_expression: DDL → DML → DQL → DCL → TCL)
DDL_TYPES = (exp.Create, exp.Alter, exp.Drop, exp.TruncateTable, exp.Schema)
DML_TYPES = (exp.Insert, exp.Update, exp.Delete, exp.Merge)
DQL_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)
DCL_TYPES = (exp.Grant, exp.Revoke)
TCL_TYPES = (exp.Commit, exp.Rollback, exp.Transaction)


class SqlStatementKind(str, Enum):
    DQL = "DQL"
    DML = "DML"
    DDL = "DDL"
    DCL = "DCL"
    TCL = "TCL"
    OTHER = "OTHER"
    BLOCKED = "BLOCKED"


@dataclass
class Tier1Result:
    """Output of static analysis (no DB connection)."""

    ok: bool
    kind: SqlStatementKind = SqlStatementKind.OTHER
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.kind == SqlStatementKind.BLOCKED or bool(self.errors)


@dataclass
class SqlVerifyResult:
    """Full result of ``verify_sql_for_preview``."""

    success: bool
    error_message: str = ""
    explain_summary: str = ""
    statement_kind: SqlStatementKind = SqlStatementKind.OTHER
    verify_tier: VerifyTier = "none"

    def as_tuple(self) -> tuple[bool, str, str]:
        """Backward-compatible (success, error_message, explain_summary)."""
        return self.success, self.error_message, self.explain_summary


def dialect_for_db_type(db_type: str) -> str:
    if db_type in {"postgresql", "postgres"}:
        return "postgres"
    return "sqlite"


def _is_create_table_as(expr: exp.Expression) -> bool:
    """CREATE [TEMP] TABLE … AS SELECT … — aligned with adapter ``is_ddl_statement`` (not DDL dry-run)."""
    return isinstance(expr, exp.Create) and isinstance(expr.expression, DQL_TYPES)


def _classify_expression(expr: exp.Expression) -> SqlStatementKind:
    # WITH cte AS (...) INSERT ... → root is still Insert (sqlglot)
    if _is_create_table_as(expr):
        return SqlStatementKind.DQL
    if isinstance(expr, DDL_TYPES):
        return SqlStatementKind.DDL
    if isinstance(expr, DML_TYPES):
        return SqlStatementKind.DML
    if isinstance(expr, DQL_TYPES):
        return SqlStatementKind.DQL
    if isinstance(expr, DCL_TYPES):
        return SqlStatementKind.DCL
    if isinstance(expr, TCL_TYPES):
        return SqlStatementKind.TCL
    return SqlStatementKind.OTHER


def _pick_verify_tier(kind: SqlStatementKind) -> VerifyTier | None:
    if kind == SqlStatementKind.DDL:
        return "tier3_ddl"
    if kind in {SqlStatementKind.DQL, SqlStatementKind.DML}:
        return "tier2_explain"
    return None


def tier1_static_analyze(sql: str, *, db_type: str = "sqlite") -> Tier1Result:
    """Tier 1: parse SQL and apply safety rules (no database connection)."""
    cleaned = strip_sql_fences((sql or "").strip()).rstrip(";")
    if not cleaned:
        return Tier1Result(
            ok=False,
            kind=SqlStatementKind.BLOCKED,
            errors=["Empty SQL statement."],
        )

    dialect = dialect_for_db_type(db_type)
    try:
        statements = sqlglot.parse(cleaned, read=dialect)
    except sqlglot.errors.ParseError as e:
        return Tier1Result(
            ok=False,
            kind=SqlStatementKind.BLOCKED,
            errors=[f"SQL parse error: {e}"],
        )

    if not statements:
        return Tier1Result(
            ok=False,
            kind=SqlStatementKind.BLOCKED,
            errors=["Could not parse SQL."],
        )

    expr = statements[0]
    kind = _classify_expression(expr)
    warnings: list[str] = []
    errors: list[str] = []

    if len(statements) > 1:
        warnings.append(
            "Multiple SQL statements detected; only the first will be verified and executed."
        )

    for node in expr.walk():
        if isinstance(node, exp.Drop) and node.args.get("kind") == "DATABASE":
            warnings.append(
                "DROP DATABASE will remove the entire database. Confirm this is intended."
            )
        if isinstance(node, exp.Drop) and node.args.get("kind") == "SCHEMA":
            warnings.append(
                "DROP SCHEMA will remove a schema and its objects. Confirm this is intended."
            )

    if isinstance(expr, exp.Delete) and not expr.args.get("where"):
        warnings.append(
            "DELETE has no WHERE clause — all rows in the table may be removed."
        )

    if isinstance(expr, exp.Update) and not expr.args.get("where"):
        warnings.append(
            "UPDATE has no WHERE clause — all rows in the table may be changed."
        )

    if isinstance(expr, exp.TruncateTable):
        warnings.append("TRUNCATE removes all rows from the table.")

    if isinstance(expr, exp.Drop) and not errors:
        warnings.append("DROP will permanently remove a table or object.")

    if _is_create_table_as(expr):
        warnings.append(
            "CREATE TABLE AS runs a SELECT to populate a new table; review the query plan below."
        )

    ok = kind != SqlStatementKind.BLOCKED and not errors
    return Tier1Result(ok=ok, kind=kind, errors=errors, warnings=warnings)


def require_dql_only(sql: str, *, db_type: str = "sqlite") -> str | None:
    """Return an error message if ``sql`` is not a single read-only SELECT/WITH statement."""
    t1 = tier1_static_analyze(sql, db_type=db_type)
    if t1.blocked:
        return t1.errors[0] if t1.errors else "SQL blocked by static checks."
    if t1.kind != SqlStatementKind.DQL:
        return (
            f"Only read-only SELECT queries are allowed here (got {t1.kind.value}). "
            "Use INSERT/UPDATE/DELETE flows that require approval for writes."
        )
    return None


async def tier2_explain_verify(
    agent,
    call_tool: Callable[..., Awaitable[str]],
    *,
    sql: str,
) -> tuple[bool, str, str]:
    """Tier 2: one ``explain_sql`` call — validity + plan text (no PREPARE, no execute)."""
    logger.info("[SqlVerify] Tier2 → MCP explain_sql")
    try:
        explain_raw = await call_tool(agent, "explain_sql", {"sql": sql})
    except Exception as e:
        return False, f"Error explaining SQL: {e}", ""

    etxt = str(explain_raw or "").strip()
    if is_sql_tool_error(etxt):
        return False, etxt, ""

    return True, "", etxt


async def tier3_ddl_verify(
    agent,
    call_tool: Callable[..., Awaitable[str]],
    *,
    sql: str,
) -> tuple[bool, str]:
    """Tier 3: ``validate_sql`` dry-run + rollback (CREATE/ALTER/DROP/TRUNCATE)."""
    logger.info("[SqlVerify] Tier3 → MCP validate_sql (DDL dry-run)")
    try:
        validation = await call_tool(agent, "validate_sql", {"sql": sql})
    except Exception as e:
        return False, f"SQL validation error: {e}"
    vtxt = str(validation or "").strip()
    if is_sql_tool_error(vtxt):
        return False, vtxt
    return True, ""


def _format_tier1_failure(t1: Tier1Result) -> str:
    parts = list(t1.errors)
    if t1.warnings:
        parts.extend(f"Warning: {w}" for w in t1.warnings)
    return "\n".join(parts) if parts else "SQL blocked by static checks."


def _unsupported_kind_user_message(kind: SqlStatementKind) -> str:
    """Plain-language message when preview cannot verify this statement class."""
    if kind == SqlStatementKind.TCL:
        return (
            "This chatbot does not support transaction control statements "
            "(BEGIN, COMMIT, ROLLBACK)."
        )
    if kind == SqlStatementKind.DCL:
        return (
            "This chatbot does not support privilege statements (GRANT, REVOKE)."
        )
    if kind == SqlStatementKind.OTHER:
        return (
            "This SQL is not supported for preview here. "
        )
    return (
        f"This type of SQL ({kind.value}) cannot be checked automatically in chat. "
        "Rephrase your request as a supported query or table change."
    )


def _error_with_warnings(message: str, warnings: list[str]) -> str:
    if not warnings:
        return message
    block = "\n".join(f"{w}" for w in warnings)
    return f"{message}\n\n{block}".strip()


def _append_warnings(summary: str, warnings: list[str]) -> str:
    if not warnings:
        return summary
    block = "\n".join(f"{w}" for w in warnings)
    return f"{summary}\n\n{block}".strip() if summary else block


async def _run_db_verify(
    agent,
    call_tool: Callable[..., Awaitable[str]],
    *,
    sql: str,
    kind: SqlStatementKind,
) -> tuple[bool, str, str, VerifyTier]:
    """Tier 2 or 3 on the connected database."""
    tier = _pick_verify_tier(kind)
    if tier == "tier3_ddl":
        ok, err = await tier3_ddl_verify(agent, call_tool, sql=sql)
        if not ok:
            return False, err, "", "tier3_ddl"
        return (
            True,
            "",
            "(Table structure change — verified with a dry-run, not applied yet.)",
            "tier3_ddl",
        )
    if tier == "tier2_explain":
        ok, err, explain_raw = await tier2_explain_verify(agent, call_tool, sql=sql)
        return ok, err, explain_raw, "tier2_explain"
    return False, _unsupported_kind_user_message(kind), "", "none"


async def verify_sql_for_preview(
    agent,
    llm,
    call_tool: Callable[..., Awaitable[str]],
    *,
    sql: str,
    operation: str,
    request: str,
    db_type: str | None = None,
) -> SqlVerifyResult:
    """Run Tier 1 → Tier 2 or Tier 3 → natural-language summary."""
    fallback_db_type = db_type or detect_db_type(agent)
    db_type = effective_db_type_for_sql(sql, fallback_db_type)
    snippet = _sql_log_snippet(sql)
    logger.info(
        "[SqlVerify] start operation=%s db_type=%s sql=%r",
        operation,
        db_type,
        snippet,
    )

    t1 = tier1_static_analyze(sql, db_type=db_type)
    db_tier = _pick_verify_tier(t1.kind)
    logger.info(
        "[SqlVerify] Tier1 kind=%s blocked=%s db_tier=%s warnings=%d",
        t1.kind.value,
        t1.blocked,
        db_tier or "none",
        len(t1.warnings),
    )
    if t1.warnings:
        for w in t1.warnings:
            logger.info("[SqlVerify] Tier1 warning: %s", w)

    if t1.blocked:
        logger.info("[SqlVerify] stop at Tier1 (blocked)")
        return SqlVerifyResult(
            success=False,
            error_message=_format_tier1_failure(t1),
            statement_kind=t1.kind,
            verify_tier="tier1",
        )

    if db_tier:
        logger.info("[SqlVerify] Tier%s next", "2 (explain)" if db_tier == "tier2_explain" else "3 (ddl)")
    else:
        logger.info("[SqlVerify] no Tier2/3 for kind=%s", t1.kind.value)

    ok, err, explain_raw, tier = await _run_db_verify(
        agent, call_tool, sql=sql, kind=t1.kind
    )
    if not ok:
        logger.info(
            "[SqlVerify] failed verify_tier=%s kind=%s error=%s",
            tier,
            t1.kind.value,
            _sql_log_snippet(err, max_len=300),
        )
        warnings = t1.warnings
        if t1.kind in {SqlStatementKind.DCL, SqlStatementKind.TCL}:
            warnings = []
        return SqlVerifyResult(
            success=False,
            error_message=_error_with_warnings(err, warnings),
            statement_kind=t1.kind,
            verify_tier=tier,
        )

    logger.info(
        "[SqlVerify] ok verify_tier=%s kind=%s explain_chars=%d",
        tier,
        t1.kind.value,
        len(explain_raw or ""),
    )

    explain_summary = ""
    try:
        explain_summary = await describe_explain_plan_naturally(
            llm,
            operation=operation,
            request=request,
            sql=sql,
            explain_raw=explain_raw,
        )
    except Exception as e:
        logger.warning("Natural-language summary failed: %s", e)

    explain_summary = _append_warnings(explain_summary, t1.warnings)
    return SqlVerifyResult(
        success=True,
        explain_summary=explain_summary,
        statement_kind=t1.kind,
        verify_tier=tier,
    )
