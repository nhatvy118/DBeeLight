"""Parse uploaded files into structured payloads for chunking."""

from __future__ import annotations

import csv
import logging
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


@dataclass
class ParsedFile:
    kind: Kind
    filename: str
    mime_type: str
    summary: str
    # tabular: list of {sheet_or_label, columns, sample_rows (list of dict)}
    tabular_sheets: list[dict[str, Any]] = field(default_factory=list)
    # document: list of {page or section, text}
    document_parts: list[dict[str, Any]] = field(default_factory=list)


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample[:8192], delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def parse_file(path: Path, filename: str, mime_type: str) -> ParsedFile:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if mime_type == "application/pdf" or ext == "pdf":
        return _parse_pdf(path, filename, mime_type)
    if mime_type in ("text/csv",) or ext == "csv":
        return _parse_csv(path, filename, mime_type)
    if (
        "spreadsheet" in mime_type
        or ext in ("xlsx", "xlsm", "xltx", "xltm")
        or (ext == "xls" and PANDAS_AVAILABLE)
    ):
        return _parse_excel(path, filename, mime_type)
    if mime_type == "application/x-sqlite3" or ext == "db":
        return _parse_sqlite(path, filename, mime_type)
    if mime_type.startswith("text/") or ext in ("txt", "md", "markdown"):
        return _parse_plain(path, filename, mime_type)

    # default: try utf-8 text
    try:
        return _parse_plain(path, filename, mime_type or "text/plain")
    except Exception:
        raise ValueError(f"Unsupported file type: {mime_type} / {ext}") from None


def _parse_csv(path: Path, filename: str, mime_type: str) -> ParsedFile:
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for CSV parsing")
    sample = path.read_text(encoding="utf-8", errors="replace")[:8192]
    delim = _detect_delimiter(sample)
    df = pd.read_csv(path, delimiter=delim)
    cols = [str(c) for c in df.columns.tolist()]
    sample_rows = df.head(5).to_dict(orient="records")
    summary = f"CSV with columns: {', '.join(cols)} ({len(df)} rows)."
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or "text/csv",
        summary=summary,
        tabular_sheets=[
            {
                "label": "Sheet1",
                "columns": cols,
                "dataframe": df,
            }
        ],
    )


def _parse_excel(path: Path, filename: str, mime_type: str) -> ParsedFile:
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required for Excel parsing")
    xl = pd.ExcelFile(path)
    sheets: list[dict[str, Any]] = []
    parts: list[str] = []
    for name in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=name)
        cols = [str(c) for c in df.columns.tolist()]
        sheets.append({"label": name, "columns": cols, "dataframe": df})
        parts.append(f"{name}: {len(df)} rows, columns {cols}")
    summary = f"Excel workbook {filename}: " + "; ".join(parts)
    return ParsedFile(
        kind="tabular",
        filename=filename,
        mime_type=mime_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        summary=summary,
        tabular_sheets=sheets,
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
