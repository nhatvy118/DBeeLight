"""Saved-chart service — save a chart to a project's dashboard, and render the dashboard
live (re-run each chart's SQL on view).

The chart SQL must be read-only (DQL); this is enforced on BOTH save and render so a saved
chart can never run a mutation. db_url is resolved server-side from project_id (never trusted
from the client), so the saved chart always runs against the project's current DB.
"""
from __future__ import annotations

import json
import logging

from app.agent.graph.dbtools import require_dql_only
from app.agent.pool import get_connection_pool
from app.features.charts import repository as repo
from app.features.projects import service as proj_service

logger = logging.getLogger("features.charts.service")

_MAX_ROWS = 5000
_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"


class ChartError(Exception):
    pass


async def _project_adapter(project_id: str, user_id: str):
    """Resolve the project's DB (ownership-checked) → pooled adapter. db_url stays server-side."""
    db_url = await proj_service.resolve_db_url(project_id, user_id)
    if not db_url:
        raise ChartError("Project has no database connected.")
    return await get_connection_pool().adapter_for(project_id, db_url)


async def save_chart(user_id: str, project_id: str, body: dict) -> dict:
    sql = (body.get("sql") or "").strip()
    mark = (body.get("mark") or "").strip()
    encoding = body.get("encoding")
    if not sql or not mark or not isinstance(encoding, dict) or not encoding:
        raise ChartError("A chart needs sql, mark and encoding.")
    adapter = await _project_adapter(project_id, user_id)  # validates project + db
    err = require_dql_only(sql, adapter.engine_name)
    if err:
        raise ChartError(f"Only a read-only SELECT can be saved as a chart: {err}")
    # Idempotent: the same SQL + mark in this project is already on the dashboard → don't duplicate.
    existing = await repo.find_chart(project_id, user_id, sql, mark)
    if existing:
        return {**existing, "already": True}
    chart = await repo.insert_chart(
        user_id, project_id,
        title=(body.get("title") or "").strip(),
        sql=sql, mark=mark, encoding=encoding,
        transform=body.get("transform"), layout=body.get("layout"),
    )
    return {**chart, "already": False}


async def delete_chart(chart_id: str, user_id: str) -> bool:
    return await repo.delete_chart(chart_id, user_id)


async def update_chart(user_id: str, chart_id: str, body: dict) -> None:
    """Edit a saved chart's title / SQL / layout. If the SQL changes it is re-verified DQL-only."""
    chart = await repo.get_chart(chart_id, user_id)
    if not chart:
        raise ChartError("Chart not found.")
    new_sql = body.get("sql")
    if new_sql is not None:
        new_sql = new_sql.strip()
        if not new_sql:
            raise ChartError("SQL cannot be empty.")
        adapter = await _project_adapter(chart["project_id"], user_id)
        err = require_dql_only(new_sql, adapter.engine_name)
        if err:
            raise ChartError(f"Only a read-only SELECT is allowed: {err}")
    title = body.get("title")
    layout = body.get("layout", chart.get("layout"))
    await repo.update_chart(
        chart_id, user_id,
        title=(title if title is not None else chart["title"]),
        sql=(new_sql if new_sql is not None else chart["sql"]),
        layout=layout,
    )


async def reorder(user_id: str, project_id: str, chart_ids: list[str]) -> None:
    await repo.set_positions(project_id, user_id, chart_ids)


async def list_charts(project_id: str, user_id: str) -> list[dict]:
    out = []
    for c in await repo.list_for_project(project_id, user_id):
        out.append({
            "id": c["id"], "title": c["title"], "mark": c["mark"],
            "layout": c.get("layout"), "sql": c["sql"],
        })
    return out


def _build_spec(columns, rows, mark, encoding, transform, title, layout) -> str:
    values = [dict(zip(columns, r)) for r in rows[:_MAX_ROWS]]
    spec: dict = {"$schema": _SCHEMA, "data": {"values": values}, "mark": mark, "encoding": encoding}
    if title:
        spec["title"] = title
    if transform:
        spec["transform"] = transform
    if layout in ("full", "half"):
        spec["usermeta"] = {"layout": layout}
    return json.dumps(spec, default=str)


async def render_dashboard(user_id: str, project_id: str) -> list[dict]:
    """Re-run every saved chart's SQL → fresh Vega-Lite specs. One row per chart; a chart
    whose SQL fails (e.g. the schema changed) returns an `error` instead of a spec."""
    charts = await repo.list_for_project(project_id, user_id)
    if not charts:
        return []
    adapter = await _project_adapter(project_id, user_id)
    out: list[dict] = []
    for c in charts:
        encoding = json.loads(c["encoding"]) if isinstance(c["encoding"], str) else (c["encoding"] or {})
        transform = json.loads(c["transform"]) if c.get("transform") else None
        item = {"id": c["id"], "title": c["title"], "layout": c.get("layout"), "sql": c["sql"]}
        err = require_dql_only(c["sql"], adapter.engine_name)
        if err:
            out.append({**item, "error": f"Chart SQL is not read-only: {err}"})
            continue
        try:
            res = await adapter.execute(c["sql"])
            item["spec"] = _build_spec(res.columns, res.rows, c["mark"], encoding, transform, c["title"], c.get("layout"))
        except Exception as e:  # noqa: BLE001
            item["error"] = str(e)
        out.append(item)
    return out
