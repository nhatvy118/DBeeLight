"""Adapter PostgreSQL (asyncpg)."""
from __future__ import annotations

from app.agent.adapters.base import Column, DatabaseAdapter


class PostgresAdapter(DatabaseAdapter):
    engine_name = "postgresql"

    async def list_tables(self) -> list[str]:
        res = await self.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        tables = [r[0] for r in res.rows]
        return self._filter_allowed(tables)

    async def describe_table(self, table_name: str) -> list[Column]:
        res = await self.execute(
            """
            SELECT c.column_name, c.data_type, c.is_nullable,
                   COALESCE(pk.is_pk, false) AS is_pk
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT kcu.column_name, true AS is_pk
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = :t AND tc.constraint_type = 'PRIMARY KEY'
            ) pk ON pk.column_name = c.column_name
            WHERE c.table_name = :t AND c.table_schema = 'public'
            ORDER BY c.ordinal_position
            """,
            {"t": table_name},
        )
        return [
            Column(name=r[0], type=r[1] or "", nullable=(r[2] == "YES"), pk=bool(r[3]))
            for r in res.rows
        ]

    async def explain(self, sql: str) -> str:
        res = await self.execute(f"EXPLAIN {sql}")
        return "\n".join(str(r[0]) for r in res.rows)
