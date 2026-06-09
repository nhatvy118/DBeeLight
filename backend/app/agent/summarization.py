"""Summarize long conversations (lean version, no langmem needed).

Same goal as the old chat_graph: keep the context bounded when history grows — summarize
the older turns into a "running summary" and keep the most recent turns verbatim. Stateless:
recomputed from history on each request (history is the source of truth in Postgres).
"""
from __future__ import annotations

import logging

from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.summarization")

TRIGGER_TOKENS = 6000      # below this threshold → no summarization
KEEP_RECENT = 6            # number of most recent turns to keep verbatim


def _approx_tokens(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages) // 4


def summarize(history: list[dict]) -> tuple[str, list[dict]]:
    """Return (summary, recent_history).

    Short history → ("", history). Long → summarize the older part, keep the last KEEP_RECENT turns.
    """
    # Short history → no summary needed.
    if not history or _approx_tokens(history) < TRIGGER_TOKENS:
        return "", history

    older = history[:-KEEP_RECENT] if len(history) > KEEP_RECENT else []
    recent = history[-KEEP_RECENT:]
    if not older:
        return "", history

    convo = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in older
        if m.get("role") in ("user", "assistant") and m.get("content")
    )
    try:
        client = get_llm()
        resp = client.chat.completions.create(
            model=get_settings().llm_model,
            messages=[
                {"role": "system", "content": (
                    "Briefly summarize the database-related conversation below, keeping the "
                    "important tables/columns/conditions/intent so later turns retain context."
                )},
                {"role": "user", "content": convo},
            ],
            temperature=0,
        )
        summary = (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("Summarization failed (%s) — using raw history", e)
        return "", history
    return summary, recent
