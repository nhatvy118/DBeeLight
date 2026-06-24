"""Adapter SQLite (aiosqlite)."""
from __future__ import annotations

from app.agent.adapters.base import Column, DatabaseAdapter


class SQLiteAdapter(DatabaseAdapter):
    engine_name = "sqlite"

    async def get_schema(self) -> dict[str, list[Column]]:
        # Columns (+ default) in ONE query via the pragma_table_info table-valued function
        # (SQLite ≥ 3.16): m.name, p.name, p.type, p."notnull", p.pk, p.dflt_value.
        res = await self.execute(
            'SELECT m.name, p.name, p.type, p."notnull", p.pk, p.dflt_value '
            "FROM sqlite_master m JOIN pragma_table_info(m.name) p "
            "WHERE m.type='table' AND m.name NOT LIKE 'sqlite_%' "
            "ORDER BY m.name, p.cid"
        )
        out: dict[str, list[Column]] = {}
        by_name: dict[str, dict[str, Column]] = {}
        for t, col, typ, notnull, pk, dflt in res.rows:
            ispk = bool(pk)
            c = Column(
                name=col, type=typ or "", nullable=not bool(notnull) and not ispk,
                pk=ispk, default=(str(dflt) if dflt is not None else None),
            )
            out.setdefault(t, []).append(c)
            by_name.setdefault(t, {})[col] = c

        # FK + single-column UNIQUE come from per-table PRAGMAs (no bulk form in SQLite).
        # Materialise the table list first — issuing a PRAGMA mid-iteration would clobber the cursor.
        for t in list(out.keys()):
            for fk in (await self.execute(f'PRAGMA foreign_key_list("{t}")')).rows:
                # id, seq, table, from, to, on_update, on_delete, match
                col = by_name[t].get(fk[3])
                if col is not None and col.references is None:
                    col.references = f"{fk[2]}.{fk[4]}"
            for idx in (await self.execute(f'PRAGMA index_list("{t}")')).rows:
                # seq, name, unique, origin, partial — origin 'pk' is the primary key, skip it.
                iname, uniq, origin = idx[1], idx[2], idx[3]
                if not uniq or origin == "pk":
                    continue
                info = (await self.execute(f'PRAGMA index_info("{iname}")')).rows
                if len(info) == 1:  # only single-column uniqueness is a useful per-column flag
                    col = by_name[t].get(info[0][2])
                    if col is not None:
                        col.unique = True

        if self.allowed_tables is not None:
            out = {t: c for t, c in out.items() if t in self.allowed_tables}
        return out

    async def explain(self, sql: str) -> str:
        res = await self.execute(f"EXPLAIN QUERY PLAN {sql}")
        return "\n".join(str(r) for r in res.rows)
