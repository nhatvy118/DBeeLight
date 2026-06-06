"""Parse uploaded files into structured payloads for SQLite import and summaries.

Tabular loading stack (pandas = API + dtype/column cleanup, not the parser itself):

    pandas DataFrame
      ├── Excel/ODS (.xlsx, .xls, .xlsb, .ods)
      │     └── engine=\"calamine\" (python-calamine / Rust)
      │     └── fallback: pandas default engine (openpyxl / xlrd) if calamine fails
      ├── CSV/TSV (.csv, .tsv, delimited .txt)
      │     └── pd.read_csv → pandas built-in C parser (+ encoding/delimiter sniff)
      └── (future) Parquet/Arrow → pyarrow, optional pipe to DuckDB

All paths end in ``sanitize_dataframe_columns`` then ``df.to_sql`` for SQLite import.
"""

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
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


Kind = Literal["tabular", "document"]

EXCEL_EXTENSIONS = frozenset({"xlsx", "xlsm", "xls", "xlsb", "ods", "xltx", "xltm"})
DELIMITED_EXTENSIONS = frozenset({"csv", "tsv", "txt"})


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


def _is_spreadsheet_upload(filename: str, mime_type: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in EXCEL_EXTENSIONS:
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


def _looks_european(sample: str) -> bool:
    return bool(re.search(r"\d+,\d{1,2}(?:[;\s]|$)", sample))


def _read_csv_smart(path: Path) -> "pd.DataFrame":
    """Pandas API + built-in C CSV parser (encoding/delimiter/decimal sniff on top)."""
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for CSV parsing")

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "latin-1"
        for enc in ("utf-8", "cp1258", "latin-1"):
            try:
                raw.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue

    sample = raw[:8192].decode(encoding, errors="replace")
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","

    decimal = "," if sep == ";" and _looks_european(sample) else "."
    thousands = "." if decimal == "," else ","

    return sanitize_dataframe_columns(
        pd.read_csv(path, sep=sep, encoding=encoding, decimal=decimal, thousands=thousands)
    )


def _dataframe_to_sheet(label: str, df: "pd.DataFrame") -> dict[str, Any]:
    cols = [str(c) for c in df.columns.tolist()]
    return {"label": label, "columns": cols, "dataframe": df}


def _parse_excel_sheets(
    path: Path,
    filename: str,
    mime_type: str,
    *,
    engine: str | None,
) -> ParsedFile:
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for spreadsheet parsing")

    xl = pd.ExcelFile(path, engine=engine) if engine else pd.ExcelFile(path)
    names = [str(n) for n in (xl.sheet_names or []) if str(n).strip()]
    if not names:
        raise ValueError("Spreadsheet has no readable sheets.")

    sheets: list[dict[str, Any]] = []
    parts: list[str] = []
    for name in names:
        kwargs: dict[str, Any] = {"sheet_name": name}
        if engine:
            kwargs["engine"] = engine
        df = sanitize_dataframe_columns(pd.read_excel(path, **kwargs))
        sheets.append(_dataframe_to_sheet(name, df))
        parts.append(f"{name}: {len(df)} rows, columns {sheets[-1]['columns']}")

    summary = f"Spreadsheet {filename}: " + "; ".join(parts)
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or _default_spreadsheet_mime(filename),
        summary=summary,
        tabular_sheets=sheets,
    )


def _parse_spreadsheet(path: Path, filename: str, mime_type: str) -> ParsedFile:
    """Pandas API; parser = calamine, then optional legacy openpyxl/xlrd."""
    try:
        return _parse_excel_sheets(path, filename, mime_type, engine="calamine")
    except Exception as e:
        logger.warning("calamine read failed for %s: %s", filename, e)
    try:
        return _parse_excel_sheets(path, filename, mime_type, engine=None)
    except Exception as e:
        raise ValueError(f"Could not read spreadsheet ({e}).") from e


def parse_file(path: Path, filename: str, mime_type: str) -> ParsedFile:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if mime_type == "application/pdf" or ext == "pdf":
        return _parse_pdf(path, filename, mime_type)
    if ext in DELIMITED_EXTENSIONS or mime_type in ("text/csv", "text/tab-separated-values"):
        return _parse_delimited(path, filename, mime_type, ext)
    if _is_spreadsheet_upload(filename, mime_type):
        return _parse_spreadsheet(path, filename, mime_type)
    if mime_type == "application/x-sqlite3" or ext == "db":
        return _parse_sqlite(path, filename, mime_type)
    if mime_type.startswith("text/") or ext in ("md", "markdown"):
        return _parse_plain(path, filename, mime_type)

    try:
        return _parse_plain(path, filename, mime_type or "text/plain")
    except Exception:
        raise ValueError(f"Unsupported file type: {mime_type} / {ext}") from None


def _parse_delimited(path: Path, filename: str, mime_type: str, ext: str) -> ParsedFile:
    if ext == "txt":
        sample = path.read_bytes()[:8192]
        if b"," not in sample and b";" not in sample and b"\t" not in sample:
            return _parse_plain(path, filename, mime_type or "text/plain")

    df = _read_csv_smart(path)
    cols = [str(c) for c in df.columns.tolist()]
    label = "Sheet1" if ext != "tsv" else "TSV1"
    summary = f"{ext.upper()} with columns: {', '.join(cols)} ({len(df)} rows)."
    mime = mime_type or ("text/tab-separated-values" if ext == "tsv" else "text/csv")
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime,
        summary=summary,
        tabular_sheets=[_dataframe_to_sheet(label, df)],
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
