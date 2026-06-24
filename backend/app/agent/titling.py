"""Generate a short session title from the first user message.

Mirrors the summarization module's shape: try the LLM, fall back to a plain
truncation if no API key / the call fails. Never raises — always returns a usable
title so callers can persist it unconditionally.
"""
from __future__ import annotations

import logging

from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.titling")

_FALLBACK = "New chat"
_MAX_LEN = 50


def _truncate(text: str, max_len: int = _MAX_LEN) -> str:
    s = (text or "").strip().replace("\n", " ")
    if not s:
        return _FALLBACK
    return (s[: max_len - 3].rstrip() + "...") if len(s) > max_len else s


async def title_from_first_message(text: str) -> str:
    """Short chat title for `text` (LLM if available, else a truncated message)."""
    s = (text or "").strip()
    if not s:
        return _FALLBACK
    try:
        resp = await get_llm().chat.completions.create(
            model=get_settings().llm_model,
            messages=[
                {"role": "system", "content": (
                    "Reply with a very short chat title (max 6-8 words) for the user message. "
                    "No quotes, no trailing punctuation."
                )},
                {"role": "user", "content": s[:2000]},
            ],
            max_tokens=30,
            temperature=0.3,
        )
        title = (resp.choices[0].message.content or "").strip()
        if title:
            return title[:80]
    except Exception as e:  # noqa: BLE001
        logger.warning("Title generation failed (%s) — using truncated message", e)
    return _truncate(s)
