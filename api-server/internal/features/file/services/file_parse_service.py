"""Parse uploaded files into structured payloads for SQLite import and summaries."""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from python_calamine import CalamineWorkbook

    CALAMINE_AVAILABLE = True
except ImportError:
    CALAMINE_AVAILABLE = False

try:
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


Kind = Literal["tabular", "document"]

# Formats read by python-calamine (Rust): xlsx/xlsm/xls/xlsb/ods + csv/tsv.
CALAMINE_EXTENSIONS = frozenset({"xlsx", "xlsm", "xls", "xlsb", "ods", "xltx", "xltm", "tsv"})


def sanitize_dataframe_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    """Unique, SQLite-safe column names (duplicate Excel headers are common)."""
    out = df.copy()
    seen: dict[str, int] = {}
    new_cols: list[str] = []
    for raw in out.columns:
        if isinstance(raw, tuple):
            base = "_".join(str(p).strip() for p in raw if str(p).strip()).strip("_")
        else:
            base = str(raw).strip() if raw is not None else ""
        base = re.sub(r"\s+", " ", base) or "column"
        if base.lower() == "nan":
            base = "column"
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        new_cols.append(base[:120])
    out.columns = new_cols
    return out


@dataclass
class ParsedFile:
    kind: Kind
    filename: str
    mime_type: str
    summary: str
    tabular_sheets: list[dict[str, Any]] = field(default_factory=list)
    document_parts: list[dict[str, Any]] = field(default_factory=list)


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample[:8192], delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _is_spreadsheet_upload(filename: str, mime_type: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in CALAMINE_EXTENSIONS:
        return True
    mime = (mime_type or "").lower()
    return "spreadsheet" in mime or "excel" in mime or "opendocument" in mime


def _default_spreadsheet_mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "ods":
        return "application/vnd.oasis.opendocument.spreadsheet"
    if ext == "xls":
        return "application/vnd.ms-excel"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sheet_rows_to_dataframe(rows: list[list[Any]]) -> "pd.DataFrame":
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for spreadsheet parsing")
    if not rows:
        return pd.DataFrame()
    width = max((len(r) for r in rows), default=0)
    normalized = [list(r) + [None] * (width - len(r)) for r in rows]
    header = [str(c).strip() if c is not None else "" for c in normalized[0]]
    if not any(h for h in header):
        header = [f"column_{i}" for i in range(width)]
    body = normalized[1:] if len(normalized) > 1 else []
    df = pd.DataFrame(body, columns=header)
    return sanitize_dataframe_columns(df)


def _parse_spreadsheet_calamine(path: Path, filename: str, mime_type: str) -> ParsedFile:
    """Primary reader: python-calamine (xlsx, xls, xlsb, ods, csv, tsv, …)."""
    if not CALAMINE_AVAILABLE:
        raise RuntimeError("python-calamine is required for spreadsheet parsing")

    wb = CalamineWorkbook.from_path(str(path))
    names = [str(n) for n in (wb.sheet_names or []) if str(n).strip()]
    if not names:
        raise ValueError("Spreadsheet has no readable sheets.")

    sheets: list[dict[str, Any]] = []
    parts: list[str] = []
    for name in names:
        sheet = wb.get_sheet_by_name(name)
        rows = sheet.to_python(skip_empty_area=False)
        df = _sheet_rows_to_dataframe(rows)
        cols = [str(c) for c in df.columns.tolist()]
        sheets.append({"label": name, "columns": cols, "dataframe": df})
        parts.append(f"{name}: {len(df)} rows, columns {cols}")

    summary = f"Spreadsheet {filename}: " + "; ".join(parts)
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or _default_spreadsheet_mime(filename),
        summary=summary,
        tabular_sheets=sheets,
    )


def _parse_spreadsheet_pandas_calamine(path: Path, filename: str, mime_type: str) -> ParsedFile:
    """Pandas wrapper around calamine engine (pandas >= 2.2)."""
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for spreadsheet parsing")
    xl = pd.ExcelFile(path, engine="calamine")
    names = [str(n) for n in (xl.sheet_names or []) if str(n).strip()]
    if not names:
        raise ValueError("Spreadsheet has no readable sheets.")

    sheets: list[dict[str, Any]] = []
    parts: list[str] = []
    for name in names:
        df = sanitize_dataframe_columns(pd.read_excel(path, sheet_name=name, engine="calamine"))
        cols = [str(c) for c in df.columns.tolist()]
        sheets.append({"label": name, "columns": cols, "dataframe": df})
        parts.append(f"{name}: {len(df)} rows, columns {cols}")

    summary = f"Spreadsheet {filename}: " + "; ".join(parts)
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or _default_spreadsheet_mime(filename),
        summary=summary,
        tabular_sheets=sheets,
    )


def _detect_excel_engine(path: Path) -> str:
    head = path.read_bytes()[:8]
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return "xlrd"
    return "openpyxl"


def _parse_spreadsheet_pandas_fallback(path: Path, filename: str, mime_type: str) -> ParsedFile:
    """Legacy fallback when calamine cannot read the file."""
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for spreadsheet parsing")

    engine = _detect_excel_engine(path)
    engines = [engine, "xlrd" if engine == "openpyxl" else "openpyxl"]
    last_err: Exception | None = None

    for eng in engines:
        try:
            xl = pd.ExcelFile(path, engine=eng)
            names = [str(n) for n in (xl.sheet_names or []) if str(n).strip()]
            if not names:
                last_err = ValueError(f"no sheets with engine={eng}")
                continue
            sheets: list[dict[str, Any]] = []
            parts: list[str] = []
            for name in names:
                df = sanitize_dataframe_columns(pd.read_excel(path, sheet_name=name, engine=eng))
                cols = [str(c) for c in df.columns.tolist()]
                sheets.append({"label": name, "columns": cols, "dataframe": df})
                parts.append(f"{name}: {len(df)} rows, columns {cols}")
            summary = f"Spreadsheet {filename}: " + "; ".join(parts)
            return ParsedFile(
                kind="tabular",
                filename=filename,
                mime_type=mime_type or _default_spreadsheet_mime(filename),
                summary=summary,
                tabular_sheets=sheets,
            )
        except Exception as e:
            last_err = e
            logger.warning("Spreadsheet fallback engine=%s failed for %s: %s", eng, filename, e)

    msg = str(last_err).strip() if last_err else "unknown error"
    raise ValueError(f"Could not read spreadsheet ({msg}).") from last_err


def _parse_spreadsheet(path: Path, filename: str, mime_type: str) -> ParsedFile:
    if CALAMINE_AVAILABLE:
        try:
            return _parse_spreadsheet_calamine(path, filename, mime_type)
        except Exception as e:
            logger.warning("calamine direct read failed for %s: %s", filename, e)
        try:
            return _parse_spreadsheet_pandas_calamine(path, filename, mime_type)
        except Exception as e:
            logger.warning("pandas calamine engine failed for %s: %s", filename, e)
    return _parse_spreadsheet_pandas_fallback(path, filename, mime_type)


def parse_file(path: Path, filename: str, mime_type: str) -> ParsedFile:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if mime_type == "application/pdf" or ext == "pdf":
        return _parse_pdf(path, filename, mime_type)
    if mime_type in ("text/csv",) or ext == "csv":
        return _parse_csv(path, filename, mime_type)
    if _is_spreadsheet_upload(filename, mime_type):
        return _parse_spreadsheet(path, filename, mime_type)
    if mime_type == "application/x-sqlite3" or ext == "db":
        return _parse_sqlite(path, filename, mime_type)
    if mime_type.startswith("text/") or ext in ("txt", "md", "markdown"):
        return _parse_plain(path, filename, mime_type)

    try:
        return _parse_plain(path, filename, mime_type or "text/plain")
    except Exception:
        raise ValueError(f"Unsupported file type: {mime_type} / {ext}") from None


def _parse_csv(path: Path, filename: str, mime_type: str) -> ParsedFile:
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for CSV parsing")
    sample = path.read_text(encoding="utf-8", errors="replace")[:8192]
    delim = _detect_delimiter(sample)
    df = sanitize_dataframe_columns(pd.read_csv(path, delimiter=delim))
    cols = [str(c) for c in df.columns.tolist()]
    summary = f"CSV with columns: {', '.join(cols)} ({len(df)} rows)."
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or "text/csv",
        summary=summary,
        tabular_sheets=[{"label": "Sheet1", "columns": cols, "dataframe": df}],
    )


def _parse_sqlite(path: Path, filename: str, mime_type: str) -> ParsedFile:
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for SQLite introspection")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    tabular_sheets: list[dict[str, Any]] = []
    parts: list[str] = []
    for tname in tables:
        cur.execute(f'PRAGMA table_info("{tname}")')
        cols = [row[1] for row in cur.fetchall()]
        cur.execute(f'SELECT * FROM "{tname}" LIMIT 100')
        rows = cur.fetchall()
        df = pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame(columns=cols)
        tabular_sheets.append({"label": tname, "columns": cols, "dataframe": df})
        parts.append(f"table {tname}: columns {cols}, sample {len(rows)} rows")
    conn.close()
    summary = f"SQLite database {filename}: " + "; ".join(parts)
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or "application/x-sqlite3",
        summary=summary,
        tabular_sheets=tabular_sheets,
    )


def _parse_pdf(path: Path, filename: str, mime_type: str) -> ParsedFile:
    if not PYPDF_AVAILABLE:
        raise RuntimeError("pypdf is required for PDF parsing")
    reader = PdfReader(str(path))
    parts: list[dict[str, Any]] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        parts.append({"page": i + 1, "text": text.strip()})
    summary = f"PDF {filename}, {len(reader.pages)} pages."
    return ParsedFile(
        kind="document",
        filename=filename,
        mime_type=mime_type or "application/pdf",
        summary=summary,
        document_parts=parts,
    )


def _parse_plain(path: Path, filename: str, mime_type: str) -> ParsedFile:
    text = path.read_text(encoding="utf-8", errors="replace")
    return ParsedFile(
        kind="document",
        filename=filename,
        mime_type=mime_type,
        summary=f"Text file {filename}, {len(text)} chars.",
        document_parts=[{"page": 1, "text": text}],
    )


def _sanitize_table_base(filename: str) -> str:
    base = filename.rsplit(".", 1)[0]
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", base).strip("_")
    if not s:
        s = "uploaded_data"
    if s[0].isdigit():
        s = "t_" + s
    return s[:60].lower()


def suggested_sqlite_table_names(parsed: ParsedFile) -> list[tuple[str, str]]:
    """Return list of (sheet_label, safe_table_name) for tabular imports."""
    base = _sanitize_table_base(parsed.filename)
    out: list[tuple[str, str]] = []
    for i, sheet in enumerate(parsed.tabular_sheets):
        label = str(sheet.get("label") or f"sheet{i}")
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", label).strip("_") or f"sheet{i}"
        name = f"{base}_{slug}"[:63]
        if name[0].isdigit():
            name = "t_" + name
        out.append((label, name[:63]))
    return out
