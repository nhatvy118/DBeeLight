"""Classify intent → one of 6 orchestrator branches (single LLM call)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.intent")

Route = Literal["db_readonly", "db_create_table", "db_mutation", "db_general", "excel", "chart"]
_VALID: set[str] = {"db_readonly", "db_create_table", "db_mutation", "db_general", "excel", "chart"}

ACCESS_LEVEL: dict[str, str] = {
    "db_readonly": "read_data",
    "db_create_table": "edit_data",
    "db_mutation": "edit_data",
    "db_general": "read_data",
    "excel": "read_data",
    "chart": "read_data",
}

_PROMPT = """You are a router. Pick EXACTLY ONE branch for the user request.

Branches:
1) db_readonly — SELECT, list/describe tables, schema exploration, aggregates without changing data.
2) db_create_table — create a new table.
3) db_mutation — INSERT/UPDATE/DELETE/ALTER/DROP (changes data/structure).
4) db_general — DB requests needing the general tool loop: connection info, export, anything not fitting 1-3.
5) excel — Excel/CSV file operations (formatting, formulas, in-file charts).
6) chart — draw a chart/graph (Vega-Lite) from DB data.

Return JSON: {"needs_clarification": bool, "clarification_question": str|null,
"route": "<one of the six>", "nl_query": str, "table_hint": str|null, "chart_type": str|null}
Return JSON only."""


@dataclass
class Intent:
    route: Route | None
    nl_query: str
    table_hint: str | None = None
    chart_type: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None

    @property
    def access_level(self) -> str | None:
        return ACCESS_LEVEL.get(self.route) if self.route else None


def classify(query: str, history: list[dict] | None = None) -> Intent:
    s = get_settings()
    client = get_llm()
    ctx = ""
    if history:
        rows = [
            f"{m['role']}: {m['content']}"
            for m in history[-6:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if rows:
            ctx = "\n[Context]\n" + "\n".join(rows) + "\n"
    try:
        resp = client.chat.completions.create(
            model=s.router_model,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": ctx + "\n[Message]\n" + query},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as e:  # noqa: BLE001
        logger.warning("intent classify failed, falling back to db_general: %s", e)
        data = {"route": "db_general", "nl_query": query}

    if data.get("needs_clarification"):
        return Intent(
            route=None,
            nl_query=query,
            needs_clarification=True,
            clarification_question=data.get("clarification_question") or "Could you clarify your request?",
        )
    route = str(data.get("route") or "db_general")
    if route not in _VALID:
        route = "db_general"
    return Intent(
        route=route,  # type: ignore[arg-type]
        nl_query=str(data.get("nl_query") or query),
        table_hint=(str(data["table_hint"]) if data.get("table_hint") else None),
        chart_type=(str(data["chart_type"]) if data.get("chart_type") else None),
    )
