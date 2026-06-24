"""Shared async OpenAI client. The client is stateless and safe to reuse across
requests; using the async client means LLM calls `await` instead of blocking the
event loop (which would otherwise stall every other concurrent request)."""
from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import get_settings


@lru_cache
def get_llm() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(api_key=s.openai_api_key or None)
