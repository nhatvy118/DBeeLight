"""In-process chart tools: run a read-only SELECT and build a Vega-Lite spec.

The adapter comes from the ContextVar — like db_tools, the connection is not a parameter.
"""
from __future__ import annotations

import json

from app.agent.context import get_db
from app.agent.tools.registry import tool

_VEGA_MARKS = {
    "bar": "bar",
    "line": "line",
    "area": "area",
    "point": "point",
    "scatter": "point",
}


@tool(
    description=(
        "Draw a Vega-Lite chart from DB data. Provide a SELECT query, the chart type, "
        "and the column names for the x/y axes. Returns a Vega-Lite spec (JSON)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SELECT query that fetches the data to plot"},
            "chart_type": {"type": "string", "enum": list(_VEGA_MARKS.keys())},
            "x": {"type": "string", "description": "X-axis column name"},
            "y": {"type": "string", "description": "Y-axis column name"},
            "title": {"type": "string"},
        },
        "required": ["sql", "chart_type", "x", "y"],
    },
)
async def generate_chart(sql: str, chart_type: str, x: str, y: str, title: str = "") -> str:
    db = get_db()
    adapter = db.any_adapter
    if adapter is None:
        return "No database connected."
    res = await adapter.execute(sql)
    values = [dict(zip(res.columns, row)) for row in res.rows]
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title or None,
        "data": {"values": values},
        "mark": _VEGA_MARKS.get(chart_type, "bar"),
        "encoding": {
            "x": {"field": x, "type": "nominal"},
            "y": {"field": y, "type": "quantitative"},
        },
    }
    return "[VEGA_LITE_SPEC]\n" + json.dumps(spec, default=str) + "\n[/VEGA_LITE_SPEC]"


CHART_TOOL_NAMES = ["generate_chart"]
