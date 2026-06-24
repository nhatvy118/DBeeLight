"""Natural-language answer for read-only results.

The read-only path ships a structured {columns, rows} result that the FE renders as a table. On
its own that leaves a "How many orders?" answered by just a one-cell table — so here we ask the
LLM to answer the question in words from the result (e.g. "There are 42 orders."), letting the
question decide the length. The workflow prepends this to its message, above the SQL card.
"""
from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.nlanswer")

# Cap the rows handed to the model: a one-sentence summary never needs the full set, and large
# results would blow up the prompt. The total count still travels via `rowcount`.
_MAX_ROWS = 200

_SYSTEM = (
    "You are given a user's data question and the JSON result of a SQL query that answers it. "
    "Answer the question in natural language using the actual figures (counts, names, values) "
    "from the result. Let the question decide the length: a count or single fact needs one short "
    "sentence, while a list or comparison may need a couple of sentences — stay concise either way. "
    "Do not dump the table row by row (it is already shown to the user), and do not mention SQL, "
    "queries, columns, or JSON. If the result has no rows, say that nothing matched the question."
)


async def answer_from_result(user_message: str, result: dict) -> str:
    """Return a natural-language answer for a read-only result, or "" if it can't be produced
    (never raises — the table is still shown, so a missing answer degrades gracefully)."""
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    rowcount = result.get("rowcount", len(rows))
    sample = rows[:_MAX_ROWS]
    payload = {
        "columns": columns,
        "rowcount": rowcount,
        "rows": sample,
        "truncated": len(rows) > len(sample),
    }
    msgs: list[dict] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"Question: {user_message}\n"
            f"Result:\n{json.dumps(payload, ensure_ascii=False, default=str)}"
        )},
    ]
    try:
        resp = await get_llm().chat.completions.create(
            model=get_settings().llm_model, messages=cast(Any, msgs), temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001 — answer is best-effort; the table already carries the data
        logger.warning("nl answer generation failed: %s", e)
        return ""
