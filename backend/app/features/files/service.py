"""Upload a file → one of three single-purpose imports (see save_and_import `mode`):

- "project_db": import the table into the project DB — a real project table (queried via the
  primary adapter). No disk file, no `files` row.
- "qa":         import the table into the session SQLite sandbox — queried by the agent via the
  session adapter (DbContext.session). Recorded as a `files` row; no disk file.
- "excel":      keep the original workbook on the shared volume so the excel-server (HTTP) can
  read/edit it. No SQL import. Recorded as a `files` row with only the disk path.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import re
import uuid
from io import BytesIO
from pathlib import Path

from app.config import get_settings
from app.features.files import repository as repo

logger = logging.getLogger("files")

# Delimited text (CSV/TSV/delimited TXT) + the Excel-family formats calamine/openpyxl/xlrd read.
_DELIMITED_EXTS = (".csv", ".tsv", ".txt")
_EXCEL_EXTS = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".xltx", ".xltm")
_TABULAR_EXTS = _DELIMITED_EXTS + _EXCEL_EXTS
# Anything tabular can be served to the Excel tools (converted to .xlsx if not already).
_EXCEL_EDITABLE = _TABULAR_EXTS


class FileImportError(Exception):
    """Raised when an upload cannot be imported (e.g. non-tabular file into a DB)."""


def _table_name(filename: str, sheet: str | None = None) -> str:
    """t_<filestem>, suffixed with the sheet name for multi-sheet workbooks."""
    stem = Path(filename).stem.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "data"
    name = f"t_{slug}"
    if sheet is not None:
        ssl = re.sub(r"[^a-z0-9_]+", "_", str(sheet).lower()).strip("_") or "sheet"
        name = f"{name}_{ssl}"
    return name[:63]


def _sanitize_columns(df):
    """Unique, SQLite-safe column names (duplicate Excel headers are common)."""
    seen: dict[str, int] = {}
    cols: list[str] = []
    for raw in df.columns:
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
        cols.append(base[:120])
    df = df.copy()
    df.columns = cols
    return df


def _safe_sheet_name(name: object) -> str:
    return re.sub(r"[\[\]:*?/\\]", "_", str(name)).strip()[:31] or "Sheet1"


def _looks_european(sample: str) -> bool:
    return bool(re.search(r"\d+,\d{1,2}(?:[;\s]|$)", sample))


def _read_csv_smart(content: bytes, ext: str):
    """CSV/TSV/TXT with encoding + delimiter + decimal sniffing (mirrors api-server)."""
    import pandas as pd  # lazy

    if content.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "latin-1"
        for enc in ("utf-8", "cp1258", "latin-1"):
            try:
                content.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue

    sample = content[:8192].decode(encoding, errors="replace")
    if ext == ".txt" and not any(d in sample for d in (",", ";", "\t")):
        raise FileImportError("Text file is not delimited — cannot import as a table")
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        sep = "\t" if ext == ".tsv" else ","

    decimal = "," if sep == ";" and _looks_european(sample) else "."
    thousands = "." if decimal == "," else ","
    return pd.read_csv(BytesIO(content), sep=sep, encoding=encoding, decimal=decimal, thousands=thousands)


def _read_excel_sheets(content: bytes) -> dict:
    """All sheets as {name: df}. calamine first (xlsx/xls/xlsb/ods), then pandas default."""
    import pandas as pd  # lazy

    last_err: Exception | None = None
    for engine in ("calamine", None):
        try:
            kwargs: dict = {"sheet_name": None}
            if engine:
                kwargs["engine"] = engine
            return pd.read_excel(BytesIO(content), **kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("excel read (engine=%s) failed: %s", engine, e)
    raise FileImportError(f"Could not read spreadsheet ({last_err})")


def _read_tables(ext: str, content: bytes) -> dict:
    """Parse tabular bytes into {sheet_label_or_None: DataFrame}. Delimited / single-sheet
    workbooks → key None (table name carries no sheet suffix); a multi-sheet workbook →
    one entry per sheet (each becomes its own table)."""
    if ext in _DELIMITED_EXTS:
        return {None: _sanitize_columns(_read_csv_smart(content, ext))}
    if ext in _EXCEL_EXTS:
        sheets = _read_excel_sheets(content)
        usable = {
            str(name): _sanitize_columns(df)
            for name, df in sheets.items()
            if str(name).strip() and getattr(df, "shape", (0, 0))[1] > 0
        }
        if not usable:
            raise FileImportError("Spreadsheet has no readable sheets")
        if len(usable) == 1:
            return {None: next(iter(usable.values()))}
        return usable
    raise FileImportError(f"Unsupported file type: {ext}")


def _to_xlsx_bytes(ext: str, content: bytes) -> bytes:
    """Convert a tabular file to .xlsx bytes so the (xlsx-only) excel-server can read it.
    Delimited → one sheet; Excel-family → every sheet preserved (formulas are not).

    Written via openpyxl directly rather than pandas' ExcelWriter, which is broken on
    pandas 3.0 + openpyxl 3.1 ("At least one sheet must be visible")."""
    from openpyxl import Workbook
    from openpyxl.utils.dataframe import dataframe_to_rows

    if ext in _DELIMITED_EXTS:
        sheets = {"Sheet1": _read_csv_smart(content, ext)}
    else:
        sheets = _read_excel_sheets(content)

    wb = Workbook()
    wb.remove(wb.active)  # drop the default empty sheet
    for name, df in sheets.items():
        ws = wb.create_sheet(_safe_sheet_name(name))
        for row in dataframe_to_rows(_sanitize_columns(df), index=False, header=True):
            ws.append(row)
    if not wb.sheetnames:  # nothing parsed → keep a valid (visible) workbook
        wb.create_sheet("Sheet1")
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _session_sqlite_path(session_id: str) -> Path:
    logger.info("→ _session_sqlite_path(session_id=%r)", session_id)  # autolog
    return get_settings().temp_dbs_dir / f"{session_id}.sqlite"


async def save_and_import(
    user_id: str,
    session_id: str,
    filename: str,
    content: bytes,
    *,
    mode: str,
    project_id: str | None = None,
    project_db_url: str | None = None,
) -> dict:
    """Single-purpose import per `mode`. Any failure raises FileImportError → 400:
    - "project_db": import the table into the project DB (no disk file, no `files` row).
    - "qa":         import the table into the session SQLite sandbox (Q&A; no disk file).
    - "excel":      keep the original on the shared volume for the excel-server (no SQL import).
    """
    logger.info("→ save_and_import(user_id=%r session_id=%r filename=%r mode=%r project_id=%r)", user_id, session_id, filename, mode, project_id)  # autolog
    if mode == "project_db":
        return await _import_to_project_db(filename, content, project_id, project_db_url)
    if mode == "qa":
        return await _import_to_session(user_id, session_id, filename, content)
    if mode == "excel":
        return await _save_for_excel(user_id, session_id, filename, content)
    raise FileImportError(f"Unknown import mode: {mode!r}")


async def _import_to_project_db(
    filename: str, content: bytes, project_id: str | None, project_db_url: str | None
) -> dict:
    """Import into the project DB → a real project table (queried via the pooled primary
    adapter, so chat sees it immediately). Nothing on disk, no `files` row — synthesized meta."""
    if not (project_id and project_db_url):
        raise FileImportError("No project database to import into")
    ext = Path(filename).suffix.lower()
    if ext not in _TABULAR_EXTS:
        raise FileImportError("Only CSV/Excel files can be imported into the database")
    tables = _read_tables(ext, content)  # one entry per sheet (multi-sheet → multiple tables)
    from app.agent.pool import get_connection_pool

    adapter = await get_connection_pool().adapter_for(project_id, project_db_url)
    for label, df in tables.items():
        await adapter.import_dataframe(_table_name(filename, label), df)
    return {
        "id": str(uuid.uuid4()),  # synthesized: nothing persisted in `files`
        "filename": filename,
        "size_bytes": len(content),
        "created_at": None,
    }


async def _import_to_session(user_id: str, session_id: str, filename: str, content: bytes) -> dict:
    """Import into the session SQLite sandbox (Q&A). One `files` row per sheet/table so
    session_db() gates them all into the agent's allowed tables; no file kept on disk."""
    ext = Path(filename).suffix.lower()
    if ext not in _TABULAR_EXTS:
        raise FileImportError("Only CSV/Excel files can be queried")
    tables = _read_tables(ext, content)  # one entry per sheet (multi-sheet → multiple tables)
    spath = _session_sqlite_path(session_id)
    # write via sync sqlite3 in a threadpool to avoid blocking the event loop
    import sqlite3

    def _write():
        logger.info("→ _write()")  # autolog
        con = sqlite3.connect(str(spath))
        try:
            for label, df in tables.items():
                df.to_sql(_table_name(filename, label), con, if_exists="replace", index=False)
        finally:
            con.close()

    await asyncio.to_thread(_write)

    # one row per table; the first carries the upload size, the rest 0 (avoid double-counting).
    first: dict | None = None
    for i, label in enumerate(tables):
        display = filename if label is None else f"{filename} ({label})"
        row = await repo.insert_file(
            user_id, session_id, display, None, str(spath),
            _table_name(filename, label), len(content) if i == 0 else 0,
        )
        first = first or row
    assert first is not None  # _read_tables guarantees ≥1 table
    return first


async def _save_for_excel(user_id: str, session_id: str, filename: str, content: bytes) -> dict:
    """Keep a workbook on the shared volume so the excel-server (xlsx-only) can read/edit it.
    Native .xlsx is stored as-is (preserves sheets/formulas); other tabular formats are
    converted to .xlsx. No SQL import — recorded as a `files` row with only the disk path."""
    ext = Path(filename).suffix.lower()
    if ext not in _EXCEL_EDITABLE:
        raise FileImportError("This file type can't be opened as an Excel workbook")
    if ext == ".xlsx":
        out_name, out_bytes = filename, content
    else:
        out_name = Path(filename).stem + ".xlsx"
        out_bytes = await asyncio.to_thread(_to_xlsx_bytes, ext, content)
    uploads = Path(get_settings().data_root) / "uploads" / session_id
    uploads.mkdir(parents=True, exist_ok=True)
    disk_path = uploads / out_name
    disk_path.write_bytes(out_bytes)
    return await repo.insert_file(
        user_id, session_id, out_name, str(disk_path), None, None, len(out_bytes)
    )


async def session_db(session_id: str) -> tuple[str | None, frozenset[str] | None]:
    """(session SQLite path, allowed table set) — used to attach the session adapter."""
    logger.info("→ session_db(session_id=%r)", session_id)  # autolog
    files = await repo.list_for_session(session_id)
    path = None
    tables: set[str] = set()
    for f in files:
        if f.get("sqlite_db_path") and f.get("table_name"):
            path = f["sqlite_db_path"]
            tables.add(f["table_name"])
    return path, (frozenset(tables) if tables else None)
