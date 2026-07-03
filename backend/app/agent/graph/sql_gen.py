"""Shared SQL generation: one LLM generate→verify→repair loop for BOTH the read-only
(SELECT) and the mutation (write) paths. The only difference is which statement kind is
allowed, passed via `mode`. Execution itself is just `dbtools.run(sql)` — already shared.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Literal, cast

from app.agent.graph.dbtools import classify_access, verify_with_explain, verify_for_mutation
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.sqlgen")

Mode = Literal["read", "write"]
_MAX_ATTEMPTS = 5


def strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    return re.sub(r"\n?```$", "", t).strip()


async def generate_sql(
    user_message: str, schema: str, engine: str, *, mode: Mode
) -> tuple[str, str | None, str]:
    """Generate SQL via the LLM with a verify+repair loop (up to _MAX_ATTEMPTS tries).

    mode="read"  → a single read query (classify_access + EXPLAIN).
    mode="write" → one OR MORE write statements (verify_for_mutation: classify_access + EXPLAIN,
                   rejects SELECT). Multiple statements run atomically (adapter.execute is one tx).

    Returns (sql, error, kind). error is None on success; `kind` is DQL/DML/DDL.
    """
    read = mode == "read"
    if read:
        instruction = f"Generate a single read-only {engine} query to answer the question."
    else:
        # The executor runs many statements in one transaction, so use as many as the request
        # needs. Engine note: SQLite ALTER TABLE changes one thing at a time → one ALTER per column.
        dialect_note = (
            " SQLite ALTER TABLE supports only RENAME TABLE, RENAME COLUMN, ADD COLUMN and DROP "
            "COLUMN — one action per statement (so adding several columns needs one ALTER per "
            "column). To change a column's TYPE or its constraints, ALTER cannot do it: recreate "
            "the table — CREATE a new table with the target schema, INSERT INTO it SELECT ... FROM "
            "the old table, DROP the old table, then ALTER TABLE ... RENAME TO the original name."
            if engine == "sqlite" else ""
        )
        instruction = (
            f"Generate one or more {engine} statements that edit data or schema for the request. "
            f"Use several statements separated by ';' when the request needs them.{dialect_note}"
        )
    # Ground the model to the actual schema: the request may NAME a table that doesn't exist (e.g. a
    # table that was only proposed but never created). The schema below is the source of truth.
    grounding = (
        " Use ONLY tables and columns that appear in the schema below; never assume or invent a table"
        " or column the schema does not contain. If the request targets a table/column that is not in"
        " the schema, do NOT guess — return no SQL. (You MAY create a new table only when the request"
        " is explicitly to recreate/replace one, per the note above.)"
    )
    client = get_llm()
    msgs: list[dict] = [
        {"role": "system", "content": f"{instruction}{grounding} Return SQL only, no explanation.\nSchema:\n{schema}"},
        {"role": "user", "content": user_message},
    ]
    sql, err, kind = "", "No SQL generated", ("DQL" if read else "DML")
    for _ in range(_MAX_ATTEMPTS):
        resp = await client.chat.completions.create(
            model=get_settings().llm_model, messages=cast(Any, msgs), temperature=0
        )
        sql = strip_fences(resp.choices[0].message.content or "")
        if (info := classify_access(sql, engine)).access == "invalid":
            # Both modes: no usable SQL (empty per the grounding rule, or prose/unparseable).
            # If it's still invalid after all retries, the final error reports the question
            # as not relevant to the connected database.
            logger.warning("no usable SQL from model (mode=%s): %r", mode, sql)
            err = ("Your question doesn't seem to match the data in this database — I couldn't "
                   "find the tables or columns it would need. Try asking about the data the "
                   "database actually contains, or rephrase with different names.")
        elif read:
            if info.access != "read_only":
                logger.warning("read SQL rejected as write: %r", sql)
                err = "The read-only path only allows read queries (no INSERT/UPDATE/DELETE/DDL)."
            else:
                ok, explain_err = await verify_with_explain(sql)
                if ok:
                    return sql, None, "DQL"
                err = explain_err
        else:
            ok, err, kind = await verify_for_mutation(sql, engine)
            if ok:
                return sql, None, kind
        # Correction goes back as a USER turn (feedback on the assistant's own prior answer) —
        # more reliable than stacking a second system message mid-conversation. For an empty
        # answer, do NOT demand "corrected SQL" (that would pressure the model to hallucinate
        # against the grounding rule) — ask it to re-check the schema and allow empty again.
        if info.access == "invalid":
            correction = ("You returned no usable SQL. Re-check the schema for tables/columns "
                          "that match the request (names may differ from the question's wording) "
                          "and return only the SQL. If there is truly no match, return nothing.")
        else:
            correction = (f"That SQL didn't pass validation. Error: {err}\n"
                          "Fix it and return only the corrected SQL.")
        msgs += [
            {"role": "assistant", "content": sql},
            {"role": "user", "content": correction},
        ]
    return sql, (err or "Could not generate valid SQL"), kind
