"""MCP server: SQL → Vega-Lite v5 spec.

The active database is set per turn by the orchestrator via ``chart_connect_db``
(mirrors the ``connect_sqlite``/``connect_db`` pattern of the database MCP server).
Chart tools then run SQL against that active connection and return a Vega-Lite
spec as a JSON string.

Rows themselves never enter the LLM context — only the spec.

The orchestrator validates user ownership of ``project_id`` before calling
``chart_connect_db``, so the active connection is always scoped to a project the
caller is authorized for. Defense in depth: ``_validate_db_url`` rejects schemes
outside (``sqlite``, ``postgresql``) and SQLite paths outside the configured
``CHART_SQLITE_ALLOWED_DIRS``.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("chart-server")
logging.basicConfig(level=logging.INFO)

mcp = FastMCP("chart-server")

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

DEFAULT_MAX_ROWS = int(os.environ.get("CHART_MAX_ROWS", "100000"))

_DEFAULT_SQLITE_DIRS = "/Users/pila_vyhuynh/Uni/mcp-server/api-server/databases"
ALLOWED_SQLITE_DIRS: tuple[str, ...] = tuple(
    p.rstrip("/")
    for p in os.environ.get("CHART_SQLITE_ALLOWED_DIRS", _DEFAULT_SQLITE_DIRS).split(":")
    if p.strip()
)

_TEMPORAL_RE = re.compile(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2}([ T]\d{1,2}:\d{2})?)?$")


# Module-level active connection. The orchestrator sets this via chart_connect_db
# at the start of each chat turn. Chart tools read from it.
_engine: Optional[Engine] = None
_active_db_url: Optional[str] = None


def _validate_db_url(db_url: str) -> None:
    """Reject db_urls outside the allow-list. Defense in depth — orchestrator
    is the primary enforcer; this catches misuse if the orchestrator has a bug
    or is bypassed."""
    if not db_url:
        raise ValueError("db_url is empty")
    parsed = urlparse(db_url)
    scheme = parsed.scheme.lower()
    if scheme.startswith("sqlite"):
        path = db_url[len("sqlite:///"):] if db_url.startswith("sqlite:///") else parsed.path
        path = "/" + path.lstrip("/")
        for prefix in ALLOWED_SQLITE_DIRS:
            if path.startswith(prefix + "/"):
                return
        raise ValueError(
            f"sqlite path '{path}' is outside CHART_SQLITE_ALLOWED_DIRS={ALLOWED_SQLITE_DIRS}"
        )
    if scheme in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg2", "postgres"}:
        return
    raise ValueError(f"unsupported db_url scheme: {scheme!r}")


def _require_engine() -> Engine:
    if _engine is None:
        raise RuntimeError(
            "No active database connection. The orchestrator must call "
            "chart_connect_db with the project's db_url before any chart tool."
        )
    return _engine


def _fetch_rows(sql: str, limit: int = DEFAULT_MAX_ROWS) -> list[dict[str, Any]]:
    """Execute a SELECT against the active connection and return rows."""
    engine = _require_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys())
        rows: list[dict[str, Any]] = []
        for i, r in enumerate(result):
            if i >= limit:
                logger.warning(
                    "chart-server: row limit %d hit (truncated). "
                    "Consider GROUP BY / DATE_TRUNC in the SQL.",
                    limit,
                )
                break
            rows.append({c: _to_jsonable(v) for c, v in zip(cols, r)})
        return rows


def _to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _infer_type(rows: list[dict], field: str, default: str = "nominal") -> str:
    if not rows or not field:
        return default
    sample = next((r.get(field) for r in rows if r.get(field) is not None), None)
    if sample is None:
        return default
    if isinstance(sample, bool):
        return "nominal"
    if isinstance(sample, (int, float)):
        return "quantitative"
    if isinstance(sample, str):
        if _TEMPORAL_RE.match(sample):
            return "temporal"
        return "nominal"
    return default


def _ensure_field(rows: list[dict], field: str, label: str) -> None:
    if not rows:
        return
    if field not in rows[0]:
        raise ValueError(
            f"{label}={field!r} is not a column in the SQL result "
            f"(available columns: {list(rows[0].keys())})"
        )


def _wrap_spec(
    *,
    rows: list[dict],
    mark: Any,
    encoding: dict,
    title: Optional[str],
) -> str:
    spec: dict[str, Any] = {
        "$schema": VEGA_LITE_SCHEMA,
        "data": {"values": rows},
        "mark": mark,
        "encoding": encoding,
    }
    if title:
        spec["title"] = title
    return json.dumps(spec)


# -------------------- connection / introspection --------------------


@mcp.tool()
def chart_connect_db(db_url: str) -> str:
    """Set the active database connection for chart tools.

    Called by the orchestrator at the start of each chat turn with the project's
    validated db_url. The agent must NOT call this tool itself — the connection
    is set by the system from the active project.
    """
    global _engine, _active_db_url
    _validate_db_url(db_url)
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = create_engine(db_url, future=True)
    _active_db_url = db_url
    logger.info("chart-server: active connection set to %s", db_url)
    return json.dumps({"status": "ok", "scheme": urlparse(db_url).scheme})


@mcp.tool()
def list_tables() -> str:
    """List table names available on the active database."""
    engine = _require_engine()
    insp = inspect(engine)
    return json.dumps({"tables": insp.get_table_names()})


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Describe a table: column names, types, nullability, primary key."""
    engine = _require_engine()
    insp = inspect(engine)
    cols = insp.get_columns(table_name)
    pks = set(insp.get_pk_constraint(table_name).get("constrained_columns", []) or [])
    return json.dumps({
        "table": table_name,
        "columns": [
            {
                "name": c["name"],
                "type": str(c.get("type")),
                "nullable": bool(c.get("nullable", True)),
                "primary_key": c["name"] in pks,
            }
            for c in cols
        ],
    })


# -------------------- chart tools --------------------


@mcp.tool()
def generate_line_chart(
    sql: str,
    x_field: str,
    y_field: str,
    color_field: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Line chart from a SQL result. Use for time-series and continuous trends.

    Prefer time-bucketed SQL: ``SELECT DATE_TRUNC('day', created_at) AS day,
    SUM(amount) AS revenue FROM ... GROUP BY 1 ORDER BY 1``.
    """
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    _ensure_field(rows, y_field, "y_field")
    encoding: dict[str, Any] = {
        "x": {"field": x_field, "type": _infer_type(rows, x_field, "temporal")},
        "y": {"field": y_field, "type": "quantitative"},
    }
    if color_field:
        _ensure_field(rows, color_field, "color_field")
        encoding["color"] = {"field": color_field, "type": _infer_type(rows, color_field, "nominal")}
    return _wrap_spec(rows=rows, mark="line", encoding=encoding, title=title)


@mcp.tool()
def generate_bar_chart(
    sql: str,
    x_field: str,
    y_field: str,
    color_field: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Bar chart for categorical comparisons."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    _ensure_field(rows, y_field, "y_field")
    encoding: dict[str, Any] = {
        "x": {"field": x_field, "type": _infer_type(rows, x_field, "nominal")},
        "y": {"field": y_field, "type": "quantitative"},
    }
    if color_field:
        _ensure_field(rows, color_field, "color_field")
        encoding["color"] = {"field": color_field, "type": _infer_type(rows, color_field, "nominal")}
    return _wrap_spec(rows=rows, mark="bar", encoding=encoding, title=title)


@mcp.tool()
def generate_pie_chart(
    sql: str,
    category_field: str,
    value_field: str,
    title: Optional[str] = None,
) -> str:
    """Pie chart from category + value columns. Best for ≤7 slices."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, category_field, "category_field")
    _ensure_field(rows, value_field, "value_field")
    if len(rows) > 7:
        logger.warning("pie chart with %d slices is hard to read; consider a bar chart.", len(rows))
    encoding = {
        "theta": {"field": value_field, "type": "quantitative"},
        "color": {"field": category_field, "type": "nominal"},
    }
    return _wrap_spec(rows=rows, mark={"type": "arc"}, encoding=encoding, title=title)


@mcp.tool()
def generate_scatter_chart(
    sql: str,
    x_field: str,
    y_field: str,
    color_field: Optional[str] = None,
    size_field: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Scatter plot for two numeric columns."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    _ensure_field(rows, y_field, "y_field")
    encoding: dict[str, Any] = {
        "x": {"field": x_field, "type": "quantitative"},
        "y": {"field": y_field, "type": "quantitative"},
    }
    if color_field:
        _ensure_field(rows, color_field, "color_field")
        encoding["color"] = {"field": color_field, "type": _infer_type(rows, color_field, "nominal")}
    if size_field:
        _ensure_field(rows, size_field, "size_field")
        encoding["size"] = {"field": size_field, "type": "quantitative"}
    return _wrap_spec(rows=rows, mark={"type": "point", "filled": True}, encoding=encoding, title=title)


@mcp.tool()
def generate_heatmap(
    sql: str,
    x_field: str,
    y_field: str,
    value_field: str,
    title: Optional[str] = None,
) -> str:
    """Heatmap: x × y grid colored by a numeric value."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    _ensure_field(rows, y_field, "y_field")
    _ensure_field(rows, value_field, "value_field")
    encoding = {
        "x": {"field": x_field, "type": _infer_type(rows, x_field, "nominal")},
        "y": {"field": y_field, "type": _infer_type(rows, y_field, "nominal")},
        "color": {"field": value_field, "type": "quantitative"},
    }
    return _wrap_spec(rows=rows, mark="rect", encoding=encoding, title=title)


@mcp.tool()
def generate_histogram(
    sql: str,
    x_field: str,
    max_bins: int = 30,
    title: Optional[str] = None,
) -> str:
    """Histogram: distribution of a numeric column."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    encoding = {
        "x": {"field": x_field, "type": "quantitative", "bin": {"maxbins": max_bins}},
        "y": {"aggregate": "count", "type": "quantitative"},
    }
    return _wrap_spec(rows=rows, mark="bar", encoding=encoding, title=title)


@mcp.tool()
def generate_area_chart(
    sql: str,
    x_field: str,
    y_field: str,
    color_field: Optional[str] = None,
    stacked: bool = True,
    title: Optional[str] = None,
) -> str:
    """Area chart for cumulative or part-of-whole over a continuous axis."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    _ensure_field(rows, y_field, "y_field")
    y_enc: dict[str, Any] = {"field": y_field, "type": "quantitative"}
    if color_field and not stacked:
        y_enc["stack"] = None
    encoding: dict[str, Any] = {
        "x": {"field": x_field, "type": _infer_type(rows, x_field, "temporal")},
        "y": y_enc,
    }
    if color_field:
        _ensure_field(rows, color_field, "color_field")
        encoding["color"] = {"field": color_field, "type": _infer_type(rows, color_field, "nominal")}
    return _wrap_spec(rows=rows, mark="area", encoding=encoding, title=title)


@mcp.tool()
def generate_boxplot(
    sql: str,
    x_field: str,
    y_field: str,
    title: Optional[str] = None,
) -> str:
    """Box plot: distribution of a numeric column grouped by a category."""
    rows = _fetch_rows(sql)
    _ensure_field(rows, x_field, "x_field")
    _ensure_field(rows, y_field, "y_field")
    encoding = {
        "x": {"field": x_field, "type": _infer_type(rows, x_field, "nominal")},
        "y": {"field": y_field, "type": "quantitative"},
    }
    return _wrap_spec(rows=rows, mark={"type": "boxplot", "extent": "min-max"}, encoding=encoding, title=title)


@mcp.tool()
def render_vega_lite_spec(
    sql: str,
    spec_template: str,
) -> str:
    """Escape hatch: render an arbitrary Vega-Lite spec by injecting SQL rows
    into ``spec_template['data']``.

    Use only when none of the specialized chart tools fit. Provide a valid
    Vega-Lite v5 spec as a JSON string; chart-server overwrites the ``data``
    field with rows from the SQL result.
    """
    rows = _fetch_rows(sql)
    try:
        spec = json.loads(spec_template)
    except Exception as e:
        raise ValueError(f"spec_template is not valid JSON: {e}") from e
    if not isinstance(spec, dict):
        raise ValueError("spec_template must be a JSON object")
    spec["data"] = {"values": rows}
    spec.setdefault("$schema", VEGA_LITE_SCHEMA)
    return json.dumps(spec)


if __name__ == "__main__":
    mcp.run()
