"""DEPRECATED — SQL verification moved into ``dbtools`` (pure DB/SQL, no LLM).

Import from ``app.agent.graph.dbtools`` instead. This shim only re-exports for backward
compatibility and holds no logic of its own.
"""
from __future__ import annotations

from app.agent.graph.dbtools import (
    AccessInfo,
    classify_access,
    is_read_only,
    verify_with_explain,
    verify_for_mutation,
)

__all__ = [
    "AccessInfo",
    "classify_access",
    "is_read_only",
    "verify_with_explain",
    "verify_for_mutation",
]
