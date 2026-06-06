"""Fixed schema + sample rows for chat context (replaces vector RAG for tabular files)."""

from __future__ import annotations

import json
from typing import Any

_MAX_SCHEMA_BLOCK_CHARS = 16_000
_SAMPLE_ROWS = 5


def _sample_rows_sync(engine_url: str, table_name: str, *, limit: int = _SAMPLE_ROWS) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return []
    eng = create_engine(engine_url)
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text(f'SELECT * FROM "{table_name}" LIMIT :lim'),
                {"lim": int(limit)},
            ).mappings().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            out.append(d)
        return out
    except Exception:
        return []
    finally:
        eng.dispose()


def _row_count_sync(engine_url: str, table_name: str) -> int | None:
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return None
    eng = create_engine(engine_url)
    try:
        with eng.connect() as conn:
            n = conn.execute(
                text(f'SELECT COUNT(*) AS c FROM "{table_name}"')
            ).scalar()
        return int(n) if n is not None else None
    except Exception:
        return None
    finally:
        eng.dispose()


def format_session_schema_block(tables: list[dict[str, Any]]) -> str:
    """Build ``[UPLOADED SPREADSHEET SCHEMA]`` for the LLM (no vector chunks)."""
    if not tables:
        return ""

    lines: list[str] = [
        "[UPLOADED SPREADSHEET SCHEMA]",
        "Use these EXACT SQLite table names in SELECT queries. Prefer SQL over guessing from samples.",
        "",
    ]
    used = sum(len(x) + 1 for x in lines)

    def _append(text: str) -> bool:
        nonlocal used
        if used + len(text) + 1 > _MAX_SCHEMA_BLOCK_CHARS:
            lines.append("... [schema context truncated for length]")
            return False
        lines.append(text)
        used += len(text) + 1
        return True

    for entry in tables:
        fname = str(entry.get("filename") or "unknown")
        sheet = str(entry.get("sheet") or "").strip()
        tname = str(entry.get("sqlite_table_name") or "").strip()
        cols = entry.get("columns") or []
        col_list = [str(c) for c in cols] if isinstance(cols, list) else []
        dtypes = entry.get("dtypes") or {}
        dtype_str = ", ".join(f"{c}:{dtypes[c]}" for c in col_list[:40] if c in dtypes)
        row_count = entry.get("row_count")
        samples = entry.get("sample_rows") or []

        header = f"## file: {fname}"
        if sheet:
            header += f" | sheet: {sheet}"
        if not _append(header):
            break
        if tname and not _append(f"table: `{tname}`"):
            break
        if col_list and not _append(f"columns ({len(col_list)}): {', '.join(col_list[:60])}"):
            break
        if dtype_str and not _append(f"dtypes: {dtype_str}"):
            break
        if row_count is not None and not _append(f"row_count: {row_count}"):
            break
        if samples:
            try:
                sample_json = json.dumps(samples, ensure_ascii=False, default=str)
            except Exception:
                sample_json = str(samples)
            if len(sample_json) > 4000:
                sample_json = sample_json[:4000] + "..."
            if not _append(f"sample_rows (max {_SAMPLE_ROWS}):\n{sample_json}"):
                break
        if not _append(""):
            break

    lines.append("[/UPLOADED SPREADSHEET SCHEMA]")
    return "\n".join(lines)


def _collect_columns_sync(engine_url: str, table_name: str) -> list[str]:
    try:
        from sqlalchemy import create_engine, inspect
    except ImportError:
        return []
    eng = create_engine(engine_url)
    try:
        insp = inspect(eng)
        cols = insp.get_columns(table_name)
        return [str(c["name"]) for c in cols]
    except Exception:
        return []
    finally:
        eng.dispose()


def normalize_schema_snapshot(value: Any) -> dict[str, Any] | None:
    """Parse ``files.schema_snapshot`` from DB (jsonb dict or JSON string)."""
    if isinstance(value, dict) and value.get("sqlite_table_name"):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict) and parsed.get("sqlite_table_name"):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def fetch_table_schema_entry(
    *,
    engine_url: str,
    table_name: str,
    filename: str,
    sheet: str = "",
    dtypes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Sync helper: column list + samples + row count for one imported table."""
    cols = _collect_columns_sync(engine_url, table_name)
    return {
        "filename": filename,
        "sheet": sheet,
        "sqlite_table_name": table_name,
        "columns": cols,
        "dtypes": dtypes or {},
        "row_count": _row_count_sync(engine_url, table_name),
        "sample_rows": _sample_rows_sync(engine_url, table_name),
    }
