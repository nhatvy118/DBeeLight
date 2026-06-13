"""Classify intent → one of 7 orchestrator branches (single LLM call)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.intent")

Route = Literal[
    "db_readonly", "db_create_table", "db_mutation",
    "db_general", "excel", "chart", "off_topic",
]
_VALID: set[str] = {
    "db_readonly", "db_create_table", "db_mutation",
    "db_general", "excel", "chart", "off_topic",
}
_DESTRUCTIVE: set[str] = {"db_create_table", "db_mutation"}

# Below this confidence on ANY route, force clarify so the user can add detail.
# Tune with golden-set eval. Lower → less friction, more wrong-route execution.
_LOW_CONFIDENCE_THRESHOLD: float = 0.7

ACCESS_LEVEL: dict[str, str] = {
    "db_readonly": "read_data",
    "db_create_table": "edit_data",
    "db_mutation": "edit_data",
    "db_general": "read_data",
    "excel": "read_data",
    "chart": "read_data",
    # off_topic intentionally absent — no DB access needed; access_level returns None.
}

_PROMPT = """You are an intent classifier for a database and spreadsheet assistant.
You ONLY classify the user's intent. You do NOT execute, generate SQL, or answer the request.

# Routes (pick exactly one)

- db_readonly     : Read-only DB. SELECT, joins, aggregates, schema exploration
                    (list/describe tables, INFORMATION_SCHEMA). No data or schema changes.
- db_create_table : Create a NEW table. Trigger only when intent is to create a table,
                    not when implied as a side-effect of another op.
- db_mutation     : Modifies data or schema. INSERT, UPDATE, DELETE, MERGE,
                    ALTER, DROP, TRUNCATE, RENAME. (CREATE TABLE → db_create_table.)
- db_general      : DB ops not fitting above — connection info, export, user/role
                    management, dumps, backups, admin metadata.
- excel           : Excel/CSV file ops — cell formatting, formulas, sheets,
                    in-file charts, save-as. Artifact is a file, not a DB query.
- chart           : Vega-Lite chart from DB data. Chart inside an Excel file → excel.
- off_topic       : Request is NOT about data, databases, files, or charts. Includes
                    greetings, small talk, weather, general knowledge, jokes, opinions,
                    and advice questions that do not require querying data.

# Precedence rules when intents combine

1. Destructive beats read: db_mutation / db_create_table > db_readonly.
2. "Show top N and plot" → chart (downstream agent fetches the data).
3. "Run query and save to Excel" → excel (final artifact is the file).
4. "Create table + insert sample data" → db_create_table (downstream handles the insert).
5. Truly ambiguous AND unsafe to guess → set needs_clarification=true.
6. Non-data question that mentions data nouns ("how to grow my business" even if
   sales data exists) → off_topic. Mention of a data noun is not a request to query.

# Output fields

## route
One of the seven routes above. Set to null ONLY when needs_clarification=true.

## nl_query
A clean, COMPLETE English restatement of the user's full intent, to be passed to
the downstream SQL / agent prompt.
- Language: English. Translate from any other language the user wrote in.
- Completeness: capture the user's intent in full — keep every detail, condition,
  column, and value the user gave. Do not truncate or summarize away specifics.
  There is no length limit; be as long as needed to be unambiguous.
- Resolve references: replace "that table", "those", "it", "the previous one" with
  the concrete thing from [Running summary] / [Context]. The restatement must stand
  alone without the conversation.
- Style: imperative or third-person describing what the user wants (e.g., "show
  monthly revenue for 2024", not "I want to see..." or "user wants to see...").
- Faithful to the user. Do NOT add assumptions, defaults, time ranges, limits, or
  filters the user did not specify. Do NOT write SQL.
- Empty string ("") when route=off_topic OR needs_clarification=true.

## needs_clarification
true ONLY when the request is BOTH ambiguous AND unsafe to guess (precedence rule 5).
When true:
  - route must be null
  - clarification_question must be a non-empty string
  - nl_query must be ""
false in all other cases — including when you pick a route at low confidence but
guessing is safe (e.g., a vague read query is fine to guess; downstream is read-only).

## clarification_question
The question to ask the user when needs_clarification=true; null otherwise.
- Be SPECIFIC. Name the missing piece — which table, which condition, which value,
  which time range. Do not ask vague open-ended questions like "what do you mean?".
- One question only. Do not chain multiple sub-questions.
- Match the user's language: if the user wrote in English, ask in English; if
  the user wrote in another language, ask in that language.

## table_hint
The table name if the user EXPLICITLY named a table; null otherwise.
- Use the name AS THE USER WROTE IT — do not normalize, translate, or pluralize.
- Do not infer table names from entity nouns. A sentence mentioning "customers"
  does NOT mean the table is named "customers"; only set when the user refers to
  a table by name (e.g., "from the orders table", "in customers_2024").
- null when: no table is named, OR multiple tables are named (downstream resolves),
  OR only abstract nouns appear ("the data", "everything", "that thing").

## chart_type
The chart type for route=chart, if the user specified one; null otherwise.
- Allowed values: "bar", "line", "pie", "scatter", "area", "heatmap".
- Lowercase, single word.
- null when: route is not chart, OR route is chart but the user did not specify
  a type (the renderer will pick a default).

## confidence
Your numeric certainty in this classification, in [0.0, 1.0]. Anchors:
- 1.0  : Certain. Request unambiguously fits exactly one route.
- 0.9  : Very confident. One route clearly fits; only trivial wording variation.
- 0.7  : Confident but not certain. Best-fit route clear, minor ambiguity exists.
- 0.5  : Moderate. Two plausible routes; you picked the more likely.
- 0.3  : Uncertain. Several routes plausible; you are guessing within a small set.
- 0.1  : Almost no signal — prefer needs_clarification=true at this level.

Use the FULL range honestly. Do not default to 0.9 on every request.
Output a NUMBER (not a string), rounded to one decimal place.

# Output

JSON only. No markdown fences, no commentary. Exact schema:
{
  "route": "<one of the seven, or null when needs_clarification=true>",
  "nl_query": "<English restatement, or empty string>",
  "needs_clarification": <bool>,
  "clarification_question": "<question to ask user, or null>",
  "table_hint": "<table name if user explicitly named one, else null>",
  "chart_type": "<bar|line|pie|scatter|area|heatmap if route=chart, else null>",
  "confidence": <number between 0.0 and 1.0>
}
"""


@dataclass
class Intent:
    route: Route | None
    nl_query: str
    table_hint: str | None = None
    chart_type: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = 0.5

    @property
    def access_level(self) -> str | None:
        return ACCESS_LEVEL.get(self.route) if self.route else None

    @property
    def is_destructive(self) -> bool:
        return self.route in _DESTRUCTIVE

    @property
    def is_off_topic(self) -> bool:
        return self.route == "off_topic"


def _coerce_confidence(v: object) -> float:
    """Parse confidence to a float in [0.0, 1.0]. Returns 0.5 on parse failure."""
    if v is None:
        return 0.5
    try:
        f = float(v)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0.5
    return max(0.0, min(1.0, f))


def _force_clarify(question: str, confidence: float) -> Intent:
    return Intent(
        route=None,
        nl_query="",
        needs_clarification=True,
        clarification_question=question,
        confidence=confidence,
    )


def _clarification_for_low_confidence(intent: Intent) -> str:
    """Pick a clarification message based on the (low-confidence) route the model picked."""
    if intent.is_destructive:
        return (
            "I'm not fully sure I understand — this may be a data-changing operation. "
            "Could you be more specific about the table, condition, and the new value?"
        )
    if intent.is_off_topic:
        return (
            "I'm not sure if your request is about data or something else. "
            "Could you tell me what you'd like to do — query data, work with a file, "
            "or generate a chart?"
        )
    return (
        "I'm not fully sure I understand your request. Could you add a bit more "
        "detail?"
    )


async def classify(query: str, history: list[dict] | None = None, summary: str = "") -> Intent:
    s = get_settings()
    client = get_llm()

    ctx = ""
    # Older turns are compressed into `summary`; recent turns stay verbatim. Both help
    # resolve follow-up references ("delete those") into a standalone nl_query.
    if summary:
        ctx += "\n[Running summary]\n" + summary.strip() + "\n"
    if history:
        rows = [
            f"{m['role']}: {m['content']}"
            for m in history[-6:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if rows:
            ctx += "\n[Context]\n" + "\n".join(rows) + "\n"

    try:
        resp = await client.chat.completions.create(
            model=s.router_model,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": ctx + "\n[Message]\n" + query},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as e:
        logger.warning("intent classify failed, falling back to db_general: %s", e)
        # On infra error: safest fallback is non-destructive route with confidence=0.
        return Intent(route="db_general", nl_query=query, confidence=0.0)
    
    logger.info("LLM intent classification output: %r", data)

    confidence = _coerce_confidence(data.get("confidence"))

    # Model-chosen clarify path
    if data.get("needs_clarification"):
        return _force_clarify(
            question=data.get("clarification_question") or "Could you clarify your request?",
            confidence=confidence,
        )

    route = str(data.get("route") or "db_general")
    if route not in _VALID:
        logger.warning("invalid route from LLM: %r, falling back to db_general", route)
        route = "db_general"
        confidence = min(confidence, 0.2)

    # nl_query is meaningless for off_topic — force it empty.
    nl_query = "" if route == "off_topic" else str(data.get("nl_query") or query)

    intent = Intent(
        route=route,  # type: ignore[arg-type]
        nl_query=nl_query,
        table_hint=(str(data["table_hint"]) if data.get("table_hint") else None),
        chart_type=(str(data["chart_type"]) if data.get("chart_type") else None),
        confidence=confidence,
    )

    # Universal safety gate: low confidence on ANY route → force clarify
    # so the user can add detail. We'd rather ask once than execute a wrong-route guess.
    if intent.confidence < _LOW_CONFIDENCE_THRESHOLD:
        logger.info(
            "low confidence (%.2f) on route %s, forcing clarify",
            intent.confidence, intent.route,
        )
        return _force_clarify(
            question=_clarification_for_low_confidence(intent),
            confidence=intent.confidence,
        )
    return intent