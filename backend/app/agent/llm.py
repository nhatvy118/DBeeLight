"""Shared OpenAI client. The client itself is stateless and usable from many requests."""
from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from app.config import get_settings


@lru_cache
def get_llm() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.openai_api_key or None)
