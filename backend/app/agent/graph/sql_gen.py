"""Shared SQL generation: one LLM generate→verify→repair loop for BOTH the read-only
(SELECT) and the mutation (write) paths. The only difference is which statement kind is
allowed, passed via `mode`. Execution itself is just `dbtools.run(sql)` — already shared.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Literal, cast

from app.agent.graph.dbtools import require_dql_only, tier2_explain, verify_for_mutation
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.sqlgen")

Mode = Literal["read", "write"]
_MAX_ATTEMPTS = 3


def strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    return re.sub(r"\n?```$", "", t).strip()


async def generate_sql(
    user_message: str, schema: str, engine: str, *, mode: Mode
) -> tuple[str, str | None, str]:
    """Generate ONE SQL statement via the LLM with a verify+repair loop (up to 3 tries).

    mode="read"  → must be a SELECT (require_dql_only + EXPLAIN).
    mode="write" → must be a write (verify_for_mutation: tier1 + EXPLAIN, rejects SELECT).

    Returns (sql, error, kind). error is None on success; `kind` is DQL/DML/DDL.
    """
    read = mode == "read"
    instruction = (
        f"Generate EXACTLY ONE SELECT statement ({engine}) to answer the question."
        if read else
        f"Generate EXACTLY ONE write statement (INSERT/UPDATE/DELETE/ALTER/DROP, {engine}) "
        "for the request."
    )
    client = get_llm()
    msgs: list[dict] = [
        {"role": "system", "content": f"{instruction} Return SQL only, no explanation.\nSchema:\n{schema}"},
        {"role": "user", "content": user_message},
    ]
    sql, err, kind = "", "No SQL generated", ("DQL" if read else "DML")
    for _ in range(_MAX_ATTEMPTS):
        resp = await client.chat.completions.create(
            model=get_settings().llm_model, messages=cast(Any, msgs), temperature=0
        )
        sql = strip_fences(resp.choices[0].message.content or "")
        if read:
            err = require_dql_only(sql, engine)
            if not err:
                ok, explain_err = await tier2_explain(sql)
                if ok:
                    return sql, None, "DQL"
                err = explain_err
        else:
            ok, err, kind = await verify_for_mutation(sql, engine)
            if ok:
                return sql, None, kind
        msgs += [
            {"role": "assistant", "content": sql},
            {"role": "system", "content": f"That SQL is invalid. Fix it and return SQL only.\nError: {err}"},
        ]
    return sql, (err or "Could not generate valid SQL"), kind
