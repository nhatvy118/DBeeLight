"""Unit tests for SQL-first schema snapshot and result table caps (no app import)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module(name: str, rel_path: str):
    root = Path(__file__).resolve().parents[1]
    path = root / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_sc = _load_module("schema_context_standalone", "internal/features/file/schema_context.py")
_du = _load_module("database_utils_standalone", "../mcp-client/mcp_agent/graph/database_utils.py")


def test_normalize_schema_snapshot_dict_and_json():
    d = {"sqlite_table_name": "t_x", "columns": ["a"], "row_count": 3}
    assert _sc.normalize_schema_snapshot(d) == d
    assert _sc.normalize_schema_snapshot(json.dumps(d)) == d
    assert _sc.normalize_schema_snapshot(None) is None


def test_format_session_schema_block_from_snapshot():
    entry = {
        "filename": "sales.csv",
        "sheet": "Sheet1",
        "sqlite_table_name": "sales_abc123",
        "columns": ["id", "amount"],
        "dtypes": {"id": "int64", "amount": "float64"},
        "row_count": 100,
        "sample_rows": [{"id": 1, "amount": 9.5}],
    }
    block = _sc.format_session_schema_block([entry])
    assert "[UPLOADED SPREADSHEET SCHEMA]" in block
    assert "sales_abc123" in block
    assert "row_count: 100" in block


def test_json_query_markdown_caps_at_50_with_footer():
    rows = [{"id": i, "v": i * 2} for i in range(60)]
    md = _du.json_query_rows_to_markdown_table(json.dumps(rows), max_rows=50)
    assert md is not None
    assert "Showing 50" in md


def test_json_query_markdown_shows_exact_total_when_small():
    rows = [{"id": i} for i in range(12)]
    md = _du.json_query_rows_to_markdown_table(json.dumps(rows), max_rows=50)
    assert md is not None
    assert "Showing 12 of 12 rows" in md


if __name__ == "__main__":
    test_normalize_schema_snapshot_dict_and_json()
    test_format_session_schema_block_from_snapshot()
    test_json_query_markdown_caps_at_50_with_footer()
    test_json_query_markdown_shows_exact_total_when_small()
    print("ok")
