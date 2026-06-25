"""Database adapter — wraps a SQLAlchemy AsyncEngine.

Uses an async driver (aiosqlite / asyncpg) so it does NOT block the event loop — that is why
the core path does not need asyncio.to_thread. The pool is managed by the AsyncEngine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import sqlglot
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_SQLGLOT_DIALECT = {"sqlite": "sqlite", "postgresql": "postgres"}


def _enable_sqlite_transactional_ddl(engine: AsyncEngine) -> None:
    """Make SQLite honour transactions for DDL too (so a multi-statement batch is all-or-nothing).

    The pysqlite/aiosqlite driver, left at its default isolation level, silently COMMITs before
    every DDL statement — so an ALTER inside a failed batch would NOT roll back. The fix
    (SQLAlchemy's documented recipe) is to disable the driver's implicit transaction handling and
    emit BEGIN ourselves, which restores proper transactional DDL. SQLite only — Postgres DDL is
    already transactional.
    """
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "connect")
    def _disable_pysqlite_autobegin(dbapi_connection, _record):  # noqa: ANN001
        dbapi_connection.isolation_level = None  # stop implicit BEGIN + COMMIT-before-DDL

    @event.listens_for(sync_engine, "begin")
    def _emit_begin(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN")


def split_statements(sql: str, engine: str) -> list[str]:
    """Split SQL into individual statements to run in one transaction.

    Fast path: no `;` in the body → a single statement, returned verbatim (no parsing, no
    re-rendering — keeps PRAGMA/EXPLAIN and every read query byte-identical). Only when there is
    an inner `;` do we parse with sqlglot to split safely (a `;` inside a string literal stays
    one statement). Unparseable SQL is returned as-is for the DB to reject.
    """
    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return []
    if ";" not in raw:
        return [raw]
    dialect = _SQLGLOT_DIALECT.get(engine) or None
    try:
        parts = [s for s in sqlglot.parse(raw, read=dialect) if s is not None]
    except Exception:  # noqa: BLE001 — let the DB surface the real error
        return [raw]
    if len(parts) <= 1:
        return [raw]
    return [p.sql(dialect=dialect) for p in parts]


def _json_cell(v: object) -> object:
    """Coerce a DB cell to a JSON-serializable value. Native JSON types pass through; everything
    else (Decimal, datetime/date, UUID, bytes, …) becomes its str() — so the structured result
    can be json.dumps'd into tool_events/the API response without a serialization error."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    rowcount: int = 0

    def to_dict(self) -> dict:
        return {
            "columns": self.columns,
            "rows": [[_json_cell(v) for v in r] for r in self.rows],
            "rowcount": self.rowcount,
        }


@dataclass
class Column:
    name: str
    type: str
    nullable: bool = True
    pk: bool = False
    default: str | None = None      # column DEFAULT expression, if any (mutation hint)
    unique: bool = False            # part of a single-column UNIQUE constraint (mutation hint)
    references: str | None = None   # foreign key target as "table.column" (JOIN hint)


class DatabaseAdapter(ABC):
    engine_name: str = "sql"

    def __init__(self, sqlalchemy_url: str):
        self._engine: AsyncEngine = create_async_engine(sqlalchemy_url, pool_pre_ping=True)
        if self._engine.dialect.name == "sqlite":
            _enable_sqlite_transactional_ddl(self._engine)

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> bool:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def execute(self, sql: str, params: dict | None = None) -> QueryResult:
        """Run SQL in ONE transaction (all-or-nothing). Handles one OR several statements — a
        single statement runs verbatim; multiple (e.g. SQLite needs one ALTER per column) are
        split and run in order.

        Returns the rows of the LAST statement that returned any (for SELECT), and `rowcount` =
        the TOTAL affected across all statements — so a 10-row multi-INSERT reports 10, not the
        last statement's 1."""
        statements = split_statements(sql, self.engine_name)
        columns: list[str] = []
        rows: list[tuple] = []
        total_rowcount = 0
        async with self._engine.begin() as conn:
            for stmt in statements:
                result = await conn.execute(text(stmt), params or {})
                if result.returns_rows:
                    fetched = result.fetchall()
                    columns = list(result.keys())
                    rows = [tuple(r) for r in fetched]
                    total_rowcount += len(fetched)
                else:
                    total_rowcount += result.rowcount or 0
        return QueryResult(columns=columns, rows=rows, rowcount=total_rowcount)

    async def import_dataframe(self, table_name: str, df, if_exists: str = "replace") -> None:
        """Write a pandas DataFrame as a table. Works across engines (SQLite/Postgres):
        run_sync bridges pandas' sync to_sql onto the async engine's connection."""
        async with self._engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: df.to_sql(table_name, sync_conn, if_exists=if_exists, index=False)
            )

    @abstractmethod
    async def get_schema(self) -> dict[str, list[Column]]:
        """Full schema in ONE query: {table_name: [Column, ...]} for every table.
        The single structure-introspection entry point (names/columns/types/PK all derive
        from here), so adapters need no separate list_tables/describe_table round-trips."""
        ...

    @abstractmethod
    async def explain(self, sql: str) -> str: ...
