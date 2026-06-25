"""Adapter PostgreSQL (asyncpg)."""
from __future__ import annotations

from app.agent.adapters.base import Column, DatabaseAdapter


class PostgresAdapter(DatabaseAdapter):
    engine_name = "postgresql"

    async def get_schema(self) -> dict[str, list[Column]]:
        # Columns (+ PK + default) for ALL tables in the public schema — one query.
        res = await self.execute(
            """
            SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
                   c.column_default, COALESCE(pk.is_pk, false) AS is_pk
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT tc.table_name, kcu.column_name, true AS is_pk
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
            WHERE c.table_schema = 'public'
            ORDER BY c.table_name, c.ordinal_position
            """
        )
        out: dict[str, list[Column]] = {}
        by_name: dict[tuple[str, str], Column] = {}
        for tname, col, typ, nullable, default, is_pk in res.rows:
            c = Column(name=col, type=typ or "", nullable=(nullable == "YES"),
                       pk=bool(is_pk), default=(str(default) if default is not None else None))
            out.setdefault(tname, []).append(c)
            by_name[(tname, col)] = c

        # Foreign keys (one bulk query). constraint_column_usage gives the referenced table.column.
        fks = await self.execute(
            """
            SELECT kcu.table_name, kcu.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
            """
        )
        for tname, col, ref_table, ref_col in fks.rows:
            c = by_name.get((tname, col))
            if c is not None and c.references is None:
                c.references = f"{ref_table}.{ref_col}"

        # Single-column UNIQUE constraints (one bulk query); group by constraint, keep 1-col ones.
        uq = await self.execute(
            """
            SELECT tc.constraint_name, kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'UNIQUE' AND tc.table_schema = 'public'
            """
        )
        members: dict[str, list[tuple[str, str]]] = {}
        for cname, tname, col in uq.rows:
            members.setdefault(cname, []).append((tname, col))
        for cols in members.values():
            if len(cols) == 1:
                c = by_name.get(cols[0])
                if c is not None:
                    c.unique = True

        return out

    async def explain(self, sql: str) -> str:
        res = await self.execute(f"EXPLAIN {sql}")
        return "\n".join(str(r[0]) for r in res.rows)
