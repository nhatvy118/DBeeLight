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


def _table_name(filename: str, sheet: str | None = None, file_id: str | None = None) -> str:
    """Table name for an imported file.

    Base is t_<filestem> (+ _<sheet> for multi-sheet workbooks). When `file_id` is given
    (session / Q&A import) it is woven in as t_<fileid8>_<filestem> so two uploads that share a
    filename stem get DISTINCT tables instead of one silently overwriting the other
    (df.to_sql uses if_exists="replace"). Project-DB imports pass no file_id → clean names.
    """
    stem = Path(filename).stem.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "data"
    prefix = f"t_{file_id.replace('-', '')[:8]}_" if file_id else "t_"
    name = f"{prefix}{slug}"
    if sheet is not None:
        ssl = re.sub(r"[^a-z0-9_]+", "_", str(sheet).lower()).strip("_") or "sheet"
        name = f"{name}_{ssl}"
    return name[:63]


def _project_table_name(filename: str, sheet: str | None = None) -> str:
    """Clean, file-derived table name for a project-DB import (NO t_ prefix — that prefix is
    reserved for session/file tables so the request router can tell the two apart). Ensures the
    name is a valid identifier (won't start with a digit)."""
    stem = Path(filename).stem.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "data"
    name = slug
    if sheet is not None:
        ssl = re.sub(r"[^a-z0-9_]+", "_", str(sheet).lower()).strip("_") or "sheet"
        name = f"{name}_{ssl}"
    if name[0].isdigit():
        name = f"_{name}"
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


def _safe_filename(filename: str, *, suffix: str = "") -> str:
    """Make a client-supplied filename safe to use as a single path segment.

    Strips any directory component (so '../../x' → 'x') and unsafe characters, so it can never
    escape the target directory. The caller still verifies containment as a second guard."""
    base = re.split(r"[\\/]", filename)[-1]             # last segment (handles / and \)
    base = re.sub(r"[^A-Za-z0-9._ \-()]+", "_", base)
    base = base.replace("..", "").strip(". ") or "upload"   # no parent refs, no leading/trailing dots
    if suffix and not base.lower().endswith(suffix):
        base = f"{Path(base).stem or 'upload'}{suffix}"
    return base[:200]


def _looks_european(sample: str) -> bool:
    return bool(re.search(r"\d+,\d{1,2}(?:[;\s]|$)", sample))


def _read_csv_smart(content: bytes, ext: str):
    """CSV/TSV/TXT with encoding + delimiter + decimal sniffing."""
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
    default_ws = wb.active  # may be None per the type stubs
    if default_ws is not None:
        wb.remove(default_ws)  # drop the default empty sheet
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


def _session_uploads_dir(session_id: str) -> Path:
    """Where this session's Excel workbooks live (shared with the excel-server)."""
    return Path(get_settings().data_root) / "uploads" / session_id


async def excel_file_paths(session_id: str, file_ids: list[str] | None = None) -> list[str]:
    """Relative paths ('<session>/<file>') of workbooks the excel-server can open for this session —
    injected into the Excel agent prompt so it opens/saves the RIGHT file under the session folder.

    If `file_ids` is given (the files the user picked for this turn), restrict to those workbooks so
    the agent edits the chosen file when several are uploaded. A picked set that contains no
    workbook (e.g. only Q&A files, or nothing) falls back to ALL of the session's workbooks."""
    rows = await repo.list_for_session(session_id)
    workbooks = [r for r in rows if r.get("disk_path")]
    if file_ids:
        wanted = set(file_ids)
        picked = [r for r in workbooks if str(r.get("id")) in wanted]
        if picked:
            workbooks = picked
    return [f"{session_id}/{Path(r['disk_path']).name}" for r in workbooks]


def snapshot_excel_dir(session_id: str) -> dict[str, float]:
    """{filename: mtime} of the session's .xlsx files BEFORE an excel turn, used to detect which
    workbook(s) the agent created or modified."""
    d = _session_uploads_dir(session_id)
    if not d.exists():
        return {}
    return {p.name: p.stat().st_mtime for p in d.glob("*.xlsx") if p.is_file()}


async def register_excel_outputs(
    user_id: str, session_id: str, before: dict[str, float]
) -> list[dict]:
    """After an excel turn: for each .xlsx the agent created or modified, ensure a `files` row
    exists and return a `file_export` tool_event so the FE shows an inline download card."""
    d = _session_uploads_dir(session_id)
    if not d.exists():
        return []
    by_path = {r.get("disk_path"): r for r in await repo.list_for_session(session_id)}
    out: list[dict] = []
    for p in sorted(d.glob("*.xlsx")):
        if not p.is_file():
            continue
        prev = before.get(p.name)
        if prev is not None and p.stat().st_mtime <= prev + 1e-6:
            continue  # untouched this turn
        row = by_path.get(str(p))
        if row is None:  # a NEW workbook the agent created → register it so it is listable/downloadable
            row = await repo.insert_file(
                user_id, session_id, p.name, str(p), None, None, p.stat().st_size
            )
        out.append({
            "tool": "excel", "type": "file_export",
            "payload": {"filename": p.name, "sessionFileId": row["id"]},
        })
    return out


async def save_and_import(
    user_id: str,
    session_id: str,
    filename: str,
    content: bytes,
    *,
    mode: str,
    project_id: str | None = None,
    project_db_url: str | None = None,
    target_table: str | None = None,
) -> dict:
    """Single-purpose import per `mode`. Any failure raises FileImportError → 400:
    - "project_db": import into the project DB. By default a NEW table (file-named); when
      `target_table` is given, APPEND the rows into that existing table instead.
    - "qa":         import the table into the session SQLite sandbox (Q&A; no disk file).
    - "excel":      keep the original on the shared volume for the excel-server (no SQL import).
    """
    logger.info("→ save_and_import(user_id=%r session_id=%r filename=%r mode=%r project_id=%r target_table=%r)", user_id, session_id, filename, mode, project_id, target_table)  # autolog
    if mode == "project_db":
        if target_table:
            return await _append_to_project_table(filename, content, project_id, project_db_url, target_table)
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
    # Project tables keep a clean, file-derived name (no t_). Refuse to clobber an existing table —
    # the user must rename the file or drop the table first (no silent overwrite of real data).
    targets = {label: _project_table_name(filename, label) for label in tables}
    existing = set((await adapter.get_schema()).keys())
    clash = sorted({t for t in targets.values() if t in existing})
    if clash:
        raise FileImportError(
            f"Table already exists in the database: {', '.join(clash)}. "
            "Rename the file or drop the existing table first."
        )
    created: list[dict] = []
    for label, df in tables.items():
        try:
            await adapter.import_dataframe(targets[label], df, if_exists="fail")
        except ValueError as e:  # raced with a concurrent import that just created the table
            raise FileImportError(f"Table '{targets[label]}' already exists.") from e
        created.append({"name": targets[label], "columns": [str(c) for c in df.columns]})
    return {
        "id": str(uuid.uuid4()),  # synthesized: nothing persisted in `files`
        "filename": filename,
        "size_bytes": len(content),
        "created_at": None,
        # New project tables → the FE offers a "describe this table" step (data dictionary).
        "tables": created,
    }


def _align_to_table(df, table_columns: list) -> tuple:
    """Match the uploaded DataFrame's columns to an existing table's columns by name (flexible
    import). Returns (aligned_df, missing_required) where:
      - aligned_df keeps only columns present in BOTH (renamed to the table's exact casing),
        so extra file columns are dropped and the DB fills any column the file omits;
      - missing_required lists table columns the file lacks that are NOT NULL with no default
        (and not the auto-increment PK) — i.e. ones the append would fail on.
    Matching is case-insensitive on the column name (the file's headers were already sanitized)."""
    by_lower = {str(c.name).lower(): c for c in table_columns}
    rename: dict = {}
    for raw in df.columns:
        hit = by_lower.get(str(raw).lower())
        if hit is not None:
            rename[raw] = hit.name
    aligned = df[list(rename.keys())].rename(columns=rename) if rename else df.iloc[:, :0]
    present = {c.name for c in table_columns if c.name in set(rename.values())}
    missing_required = [
        c.name for c in table_columns
        if c.name not in present and not c.nullable and c.default is None and not c.pk
    ]
    return aligned, missing_required


async def _append_to_project_table(
    filename: str, content: bytes, project_id: str | None, project_db_url: str | None,
    target_table: str,
) -> dict:
    """Append a file's rows INTO an existing project table (flexible column matching). Columns
    are matched to the target by name; extras are ignored and omitted columns fall back to the
    DB's default/NULL/auto-increment. Raises FileImportError on any problem (→ 400)."""
    if not (project_id and project_db_url):
        raise FileImportError("No project database to import into")
    ext = Path(filename).suffix.lower()
    if ext not in _TABULAR_EXTS:
        raise FileImportError("Only CSV/Excel files can be imported into the database")
    tables = _read_tables(ext, content)
    if len(tables) > 1:
        raise FileImportError(
            "This file has multiple sheets — appending supports a single table. "
            "Split the sheets or import as a new table instead."
        )
    df = next(iter(tables.values()))

    from app.agent.pool import get_connection_pool
    adapter = await get_connection_pool().adapter_for(project_id, project_db_url)
    schema = await adapter.get_schema()
    if target_table not in schema:
        raise FileImportError(f"Table '{target_table}' doesn't exist in the database.")

    aligned, missing_required = _align_to_table(df, schema[target_table])
    if aligned.shape[1] == 0:
        raise FileImportError(
            f"None of the file's columns match the columns of '{target_table}'. "
            "Check the headers or import as a new table."
        )
    if missing_required:
        raise FileImportError(
            f"The file is missing required column(s) of '{target_table}': "
            f"{', '.join(missing_required)}."
        )
    try:
        await adapter.import_dataframe(target_table, aligned, if_exists="append")
    except Exception as e:  # noqa: BLE001 — surface a clean reason, not the raw driver text
        from app.agent.graph import dbtools
        raise FileImportError(
            f"Couldn’t append to '{target_table}': {dbtools.clean_db_error(str(e))}."
        ) from e
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
    # Pin a file id per table UP FRONT so the table name can embed it (t_<id8>_<stem>) — this is
    # what makes two uploads with the same filename stem land in distinct tables.
    named = [
        (fid := str(uuid.uuid4()), label, df, _table_name(filename, label, fid))
        for label, df in tables.items()
    ]
    # write via sync sqlite3 in a threadpool to avoid blocking the event loop
    import sqlite3

    def _write():
        logger.info("→ _write()")  # autolog
        con = sqlite3.connect(str(spath))
        try:
            for _fid, _label, df, tname in named:
                df.to_sql(tname, con, if_exists="replace", index=False)
        finally:
            con.close()

    await asyncio.to_thread(_write)

    # one row per table; the first carries the upload size, the rest 0 (avoid double-counting).
    first: dict | None = None
    for i, (fid, label, _df, tname) in enumerate(named):
        display = filename if label is None else f"{filename} ({label})"
        row = await repo.insert_file(
            user_id, session_id, display, None, str(spath),
            tname, len(content) if i == 0 else 0, file_id=fid,
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
        out_name, out_bytes = _safe_filename(filename, suffix=".xlsx"), content
    else:
        out_name = _safe_filename(filename, suffix=".xlsx")
        out_bytes = await asyncio.to_thread(_to_xlsx_bytes, ext, content)
    uploads = (Path(get_settings().data_root) / "uploads" / session_id).resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    disk_path = (uploads / out_name).resolve()
    # Second guard: the resolved path MUST stay inside uploads/<session>/ (defence in depth
    # against a crafted filename that survived sanitisation).
    if uploads not in disk_path.parents:
        raise FileImportError("Invalid file name")
    disk_path.write_bytes(out_bytes)
    return await repo.insert_file(
        user_id, session_id, out_name, str(disk_path), None, None, len(out_bytes)
    )


def _drop_table(sqlite_path: str, table_name: str) -> None:
    """DROP a session table from its SQLite file (sync; run in a threadpool)."""
    import sqlite3

    con = sqlite3.connect(sqlite_path)
    try:
        con.execute(f'DROP TABLE IF EXISTS "{table_name}"')  # table_name is server-generated (safe)
        con.commit()
    finally:
        con.close()


async def delete_file(user_id: str, file_id: str) -> bool:
    """Delete a file's DB row AND its backing storage, so nothing is orphaned:
    - qa import   → DROP the session SQLite table.
    - excel import → unlink the workbook on disk.
    A backing resource is only removed when no OTHER file row still references it."""
    logger.info("→ delete_file(user_id=%r file_id=%r)", user_id, file_id)  # autolog
    row = await repo.get_file_full(file_id, user_id)
    if not row:
        return False
    await repo.delete_file(file_id, user_id)

    remaining = await repo.list_for_session(row["session_id"])
    spath, tname, dpath = row.get("sqlite_db_path"), row.get("table_name"), row.get("disk_path")

    # Drop the orphan session table (unless another row still maps to the same table).
    if spath and tname and not any(
        r.get("sqlite_db_path") == spath and r.get("table_name") == tname for r in remaining
    ):
        try:
            await asyncio.to_thread(_drop_table, spath, tname)
        except Exception as e:  # noqa: BLE001 — cleanup is best-effort, never fail the delete
            logger.warning("could not drop table %s in %s: %s", tname, spath, e)

    # Remove the on-disk workbook (unless another row still points to the same file).
    if dpath and not any(r.get("disk_path") == dpath for r in remaining):
        try:
            Path(dpath).unlink(missing_ok=True)
        except OSError as e:
            logger.warning("could not unlink %s: %s", dpath, e)
    return True


async def session_db(
    session_id: str, file_ids: list[str]
) -> tuple[str | None, frozenset[str] | None]:
    """(session SQLite path, allowed table set) for the picked uploaded files — used to attach
    the session adapter scoped to the data sources the user selected for this turn."""
    logger.info("→ session_db(session_id=%r file_ids=%r)", session_id, file_ids)  # autolog
    files = await repo.list_for_session(session_id)
    wanted = set(file_ids)
    path = None
    tables: set[str] = set()
    for f in files:
        if str(f.get("id")) not in wanted:
            continue
        if f.get("sqlite_db_path") and f.get("table_name"):
            path = f["sqlite_db_path"]
            tables.add(f["table_name"])
    return path, (frozenset(tables) if tables else None)
