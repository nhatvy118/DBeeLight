"""In-process chart tool: run a read-only SELECT and build a Vega-Lite spec.

The agent supplies the Vega-Lite `mark` + `encoding` (and optional `transform`); the
backend runs the SQL, validates the spec against the actual result columns, and injects
the data. This keeps charts flexible to the user's question (any channel / chart type /
data type) while the server stays in control of the data (no fabricated values, no
external data URLs). The DB adapter comes from the ContextVar — not a tool parameter.
"""
from __future__ import annotations

import json

from app.agent.context import get_db
from app.agent.tools.registry import tool

# Marks we render. Excludes geoshape/image (need projections / external data).
_MARKS = {
    "bar", "line", "area", "point", "circle", "square", "tick",
    "rect", "arc", "rule", "text", "trail",
}
# Vega-Lite encoding channels the agent may use.
_CHANNELS = {
    "x", "y", "x2", "y2", "xOffset", "yOffset",
    "theta", "theta2", "radius", "color", "size", "shape",
    "opacity", "strokeDash", "text", "tooltip", "detail", "order",
    "row", "column", "facet",
}
_TYPES = {"quantitative", "nominal", "ordinal", "temporal"}
_MAX_ROWS = 5000  # cap inline data so the spec/payload stays small


def _check_field_def(channel: str, defn: object, cols: set[str]) -> str | None:
    """Validate one field definition: it's an object, its field is a real column,
    and its type is a valid Vega-Lite data type."""
    if not isinstance(defn, dict):
        return f"encoding.{channel} entries must be objects like {{'field': ..., 'type': ...}}"
    field = defn.get("field")
    if field is not None and field not in cols:
        return f"encoding.{channel}.field '{field}' is not a selected column (have: {sorted(cols)})"
    vtype = defn.get("type")
    if vtype is not None and vtype not in _TYPES:
        return f"encoding.{channel}.type '{vtype}' is invalid (use: {sorted(_TYPES)})"
    return None


def _validate_encoding(encoding: object, columns: list[str]) -> str | None:
    """Return an error string if the encoding is invalid, else None. Every channel must
    be known; tooltip/detail/order may be an array of field defs, others a single def."""
    if not isinstance(encoding, dict) or not encoding:
        return "encoding must be a non-empty object mapping channels to field definitions"
    cols = set(columns)
    for channel, defn in encoding.items():
        if channel not in _CHANNELS:
            return f"unknown encoding channel '{channel}' (allowed: {sorted(_CHANNELS)})"
        # tooltip/detail/order accept a list of field definitions.
        defs = defn if isinstance(defn, list) else [defn]
        for d in defs:
            err = _check_field_def(channel, d, cols)
            if err:
                return err
    return None


@tool(
    description=(
        "Render a Vega-Lite chart from DB data. You provide a read-only SELECT plus the "
        "Vega-Lite `mark` and `encoding`; the server runs the SQL and injects the data.\n"
        "- mark: one of bar, line, area, point, circle, square, tick, rect, arc, rule, text, trail.\n"
        "- encoding: map channels to field definitions, e.g. "
        "{\"x\":{\"field\":\"month\",\"type\":\"temporal\"}, \"y\":{\"field\":\"total\",\"type\":\"quantitative\"}}. "
        "Pick the right type: temporal for dates, quantitative for numbers, nominal/ordinal for categories.\n"
        "- Multi-dimension: add channels — color (series/group), size (bubble), xOffset (grouped bar).\n"
        "- Pie: mark 'arc' with encoding {theta:{value col, quantitative}, color:{category col, nominal}}.\n"
        "- Heatmap: mark 'rect' with x (nominal/ordinal), y (nominal/ordinal), color (quantitative).\n"
        "- Aggregate in the SQL (GROUP BY) for large tables; only return the columns you encode.\n"
        "- Every encoding field MUST be a column returned by your SELECT.\n"
        "For a dashboard, call this tool multiple times — one chart per call."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "Read-only SELECT that returns exactly the columns you encode"},
            "mark": {"type": "string", "enum": sorted(_MARKS)},
            "encoding": {
                "type": "object",
                "description": "Vega-Lite encoding: channel -> {field, type, aggregate?, bin?, timeUnit?, ...}",
            },
            "transform": {
                "type": "array",
                "description": "Optional Vega-Lite transforms (aggregate/bin/filter/calculate ...)",
                "items": {"type": "object"},
            },
            "title": {"type": "string"},
            "layout": {
                "type": "string",
                "enum": ["full", "half"],
                "description": (
                    "Dashboard layout hint when emitting several charts: 'full' spans the whole "
                    "row (wide charts, time series), 'half' pairs side-by-side. Default full."
                ),
            },
        },
        "required": ["sql", "mark", "encoding"],
    },
)
async def generate_chart(
    sql: str, mark: str, encoding: dict, transform: list | None = None,
    title: str = "", layout: str = "",
) -> str:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return "No database connected."
    if mark not in _MARKS:
        return f"Unsupported mark '{mark}'. Allowed: {sorted(_MARKS)}"

    res = await adapter.execute(sql)
    err = _validate_encoding(encoding, res.columns)
    if err:
        return f"Invalid chart spec: {err}"

    values = [dict(zip(res.columns, row)) for row in res.rows[:_MAX_ROWS]]
    if not values:
        # An empty result renders a blank chart — tell the agent so it can report it
        # (e.g. wrong table/filter, or the table has no rows) instead of drawing nothing.
        return "The query returned no rows, so there is nothing to plot. Check the table name and any filters."
    spec: dict = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"values": values},
        "mark": mark,
        "encoding": encoding,
    }
    if title:
        spec["title"] = title
    if transform:
        spec["transform"] = transform
    # usermeta is passed through untouched by Vega-Lite. We stash the chart "recipe"
    # (sql + mark + encoding) so the frontend can save it to a project dashboard, plus
    # the layout hint for the dashboard grid.
    source = {"sql": sql, "mark": mark, "encoding": encoding}
    if transform:
        source["transform"] = transform
    usermeta: dict = {"source": source}
    if layout in ("full", "half"):
        usermeta["layout"] = layout
    spec["usermeta"] = usermeta
    # Raw Vega-Lite JSON (no markers). The router surfaces it as a structured
    # tool_event (type "chart"); the frontend renders from payload.spec.
    return json.dumps(spec, default=str)


CHART_TOOL_NAMES = ["generate_chart"]
