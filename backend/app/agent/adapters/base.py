"""Database adapter — wraps a SQLAlchemy AsyncEngine.

Uses an async driver (aiosqlite / asyncpg) so it does NOT block the event loop — that is why
the core path does not need asyncio.to_thread. The pool is managed by the AsyncEngine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


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

    def __init__(self, sqlalchemy_url: str, allowed_tables: frozenset[str] | None = None):
        self._engine: AsyncEngine = create_async_engine(sqlalchemy_url, pool_pre_ping=True)
        self.allowed_tables = allowed_tables

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> bool:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def execute(self, sql: str, params: dict | None = None) -> QueryResult:
        """Run any SQL. SELECT → returns rows; otherwise → rowcount."""
        async with self._engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            if result.returns_rows:
                rows = result.fetchall()
                cols = list(result.keys())
                return QueryResult(columns=cols, rows=[tuple(r) for r in rows], rowcount=len(rows))
            return QueryResult(columns=[], rows=[], rowcount=result.rowcount or 0)

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
