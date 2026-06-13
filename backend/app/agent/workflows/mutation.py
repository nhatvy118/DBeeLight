"""Mutation workflow with APPROVAL (human-in-the-loop) — stateless version (legacy/unused).

Instead of keeping a checkpoint in-process, the pending SQL is returned to the client and resent when
the user clicks Execute. This keeps the orchestrator stateless (no checkpointer needed for
this path) and safe across replicas.

Two phases:
- plan_mutation(): generate SQL + preview (not run) → return to the UI.
- execute_sql(): run SQL after the user approves.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.agent.context import get_db
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.mutation")


@dataclass
class MutationPlan:
    sql: str
    preview_markdown: str
    explain: str
    error: str | None = None


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    t = re.sub(r"\n?```$", "", t)
    return t.strip()


async def _schema_context() -> str:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return "(no db)"
    tables = await adapter.list_tables()
    blocks = []
    for t in tables[:30]:
        cols = await adapter.describe_table(t)
        cols_s = ", ".join(f"{c.name} {c.type}" for c in cols)
        blocks.append(f"- {t}({cols_s})")
    return "\n".join(blocks)


async def plan_mutation(nl_query: str, engine: str) -> MutationPlan:
    """Generate the mutation SQL + preview of affected rows. Does NOT run the mutation."""
    s = get_settings()
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return MutationPlan(sql="", preview_markdown="", explain="", error="No database connected.")

    schema = await _schema_context()
    client = get_llm()
    resp = await client.chat.completions.create(
        model=s.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    f"Generate EXACTLY ONE SQL statement ({engine}) for the request. Return SQL only, no explanation.\n"
                    f"Schema:\n{schema}"
                ),
            },
            {"role": "user", "content": nl_query},
        ],
        temperature=0,
    )
    sql = _strip_fences(resp.choices[0].message.content or "")

    # EXPLAIN to validate (does not run the mutation)
    try:
        explain = await adapter.explain(sql)
    except Exception as e:  # noqa: BLE001
        return MutationPlan(sql=sql, preview_markdown="", explain="", error=f"Invalid SQL: {e}")

    preview = await _preview(adapter, sql)
    return MutationPlan(sql=sql, preview_markdown=preview, explain=explain)


async def _preview(adapter, sql: str) -> str:
    """Preview affected rows via a derived SELECT (DELETE/UPDATE)."""
    m = re.match(r"\s*(delete|update)\s", sql, re.IGNORECASE)
    if not m:
        return "_See the SQL above. (INSERT/CREATE: preview skipped in the skeleton.)_"
    where = ""
    wm = re.search(r"\bwhere\b(.*)$", sql, re.IGNORECASE | re.DOTALL)
    if wm:
        where = " WHERE " + wm.group(1).strip().rstrip(";")
    tm = re.search(r"(?:from|update)\s+([\"`]?[A-Za-z0-9_]+[\"`]?)", sql, re.IGNORECASE)
    if not tm:
        return "_Could not infer a table to preview._"
    table = tm.group(1).strip('"`')
    try:
        res = await adapter.execute(f'SELECT * FROM "{table}"{where} LIMIT 50')
    except Exception as e:  # noqa: BLE001
        return f"_Preview error: {e}_"
    if not res.columns:
        return "_No matching rows._"
    head = "| " + " | ".join(res.columns) + " |"
    sep = "| " + " | ".join("---" for _ in res.columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in res.rows]
    return "**Rows that would be affected (preview):**\n\n" + "\n".join([head, sep, *body])


async def execute_sql(sql: str) -> str:
    """Run SQL after the user approves."""
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return "No database connected."
    try:
        res = await adapter.execute(sql)
    except Exception as e:  # noqa: BLE001
        return f"Error running SQL: {e}"
    return f"Executed successfully. ({res.rowcount} rows affected)"
