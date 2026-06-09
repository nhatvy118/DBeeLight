"""Adapter SQLite (aiosqlite)."""
from __future__ import annotations

from app.agent.adapters.base import Column, DatabaseAdapter


class SQLiteAdapter(DatabaseAdapter):
    engine_name = "sqlite"

    async def list_tables(self) -> list[str]:
        res = await self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [r[0] for r in res.rows]
        return self._filter_allowed(tables)

    async def describe_table(self, table_name: str) -> list[Column]:
        # PRAGMA does not take bind params → table_name must be safe (validated upstream).
        res = await self.execute(f'PRAGMA table_info("{table_name}")')
        cols: list[Column] = []
        for row in res.rows:
            # cid, name, type, notnull, dflt_value, pk
            cols.append(
                Column(name=row[1], type=row[2] or "", nullable=not bool(row[3]), pk=bool(row[5]))
            )
        return cols

    async def explain(self, sql: str) -> str:
        res = await self.execute(f"EXPLAIN QUERY PLAN {sql}")
        return "\n".join(str(r) for r in res.rows)
