# Streaming File Upload (OOM Fix) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the backend from OOM-crashing on large uploads by keeping upload bytes on disk, streaming CSV imports in chunks, capping Excel files at 30 MB, and moving parse work off the event loop.

**Architecture:** The upload path currently pulls the whole request body into RAM (`_read_limited` → `bytes`) and hands it to pandas, which explodes a 100 MB xlsx into multi-GB DataFrames and gets the worker OOM-killed (nginx then returns a CORS-less 502 that browsers report as a CORS error). The fix: (1) router spools the upload to a temp file on disk and passes a `Path` through the service layer; (2) CSV/TSV/TXT imports stream via `pd.read_csv(chunksize=...)` → `adapter.import_dataframe(if_exists="append")` per chunk; (3) Excel-family files keep the load-it-all parse (the format can't stream with calamine) but are capped at 30 MB with a "Save As CSV" hint; (4) all pandas parsing runs in `asyncio.to_thread` so it never blocks the event loop.

**Tech Stack:** FastAPI/Starlette `UploadFile`, pandas (`read_csv` chunked, `read_excel` via calamine), SQLAlchemy async adapters (`import_dataframe`), pytest + pytest-asyncio (`asyncio_mode = "auto"` already configured in `pyproject.toml`).

**Background docs:** `backend/app/features/files/service.py` module docstring explains the two import modes ("project_db" / "excel"). `backend/app/agent/adapters/base.py:151` is `import_dataframe`. All call sites of the changed functions live in `files/router.py` + `files/service.py` only (verified by grep).

**Working dir:** all commands run from `backend/` with the project venv (`uv run pytest ...` or `.venv/bin/pytest`).

---

## File Structure

- Modify: `backend/app/features/files/router.py` — replace `_read_limited` with `_spool_to_disk`; per-extension size caps; quota via file size; temp-file cleanup.
- Modify: `backend/app/features/files/service.py` — `save_and_import` and everything below it takes `path: Path` instead of `content: bytes`; new `_sniff_csv` + `_import_csv_streaming`; parse work wrapped in `asyncio.to_thread`.
- Create: `backend/tests/conftest.py` — shared fixtures (fake `UploadFile`, fake adapter).
- Create: `backend/tests/test_upload_spool.py` — spool-to-disk + size-cap tests.
- Create: `backend/tests/test_csv_streaming.py` — sniffing + chunked import tests.
- Create: `backend/tests/test_service_paths.py` — path-based service behavior (excel mode, xlsx passthrough).

---

### Task 1: Test scaffolding (fixtures)

**Files:**
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Write conftest with a fake UploadFile and a fake DB adapter**

```python
# backend/tests/conftest.py
"""Shared fixtures. FakeUpload mimics starlette UploadFile.read(); FakeAdapter
records import_dataframe calls so streaming tests can assert per-chunk appends
without a real database."""
from __future__ import annotations

import io

import pytest


class FakeUpload:
    """Minimal stand-in for starlette's UploadFile: async chunked .read()."""

    def __init__(self, data: bytes, filename: str = "test.csv"):
        self._buf = io.BytesIO(data)
        self.filename = filename

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


class FakeColumn:
    def __init__(self, name, nullable=True, default=None, pk=False):
        self.name, self.nullable, self.default, self.pk = name, nullable, default, pk


class FakeAdapter:
    """Records every import_dataframe call: [(table, row_count, if_exists), ...]."""

    def __init__(self, schema: dict | None = None):
        self.calls: list[tuple[str, int, str]] = []
        self._schema = schema or {}
        self.dropped: list[str] = []
        self.fail_on_call: int | None = None  # 1-based call index that raises

    async def import_dataframe(self, table_name, df, if_exists="replace"):
        if self.fail_on_call is not None and len(self.calls) + 1 == self.fail_on_call:
            raise RuntimeError("simulated mid-stream failure")
        self.calls.append((table_name, len(df), if_exists))

    async def get_schema(self):
        return self._schema

    async def execute(self, sql: str):
        if sql.upper().startswith("DROP TABLE"):
            self.dropped.append(sql)


@pytest.fixture
def fake_adapter():
    return FakeAdapter()
```

- [ ] **Step 2: Verify pytest collects (no tests yet, exit code 5 is expected)**

Run: `cd backend && uv run pytest tests/ -q`
Expected: "no tests ran" (collection succeeds, no import errors)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/__init__.py backend/tests/conftest.py
git commit -m "test: scaffolding for upload streaming tests (fake UploadFile/adapter)"
```

---

### Task 2: `_spool_to_disk` — receive uploads onto disk with per-extension caps

**Files:**
- Modify: `backend/app/features/files/router.py:20-34` (constants + `_read_limited`)
- Test: `backend/tests/test_upload_spool.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_upload_spool.py
"""_spool_to_disk must (a) write the upload to a temp file without holding it in
RAM, (b) enforce the per-extension limit and unlink the partial file on 413."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.features.files.router import _spool_to_disk, _upload_limit, _EXCEL_MAX, _QUOTA_BYTES
from tests.conftest import FakeUpload


async def test_spool_writes_file_and_returns_path():
    up = FakeUpload(b"a,b\n1,2\n" * 1000, filename="data.csv")
    path = await _spool_to_disk(up, limit=_QUOTA_BYTES)
    try:
        assert isinstance(path, Path) and path.exists()
        assert path.stat().st_size == len(b"a,b\n1,2\n") * 1000
    finally:
        path.unlink(missing_ok=True)


async def test_spool_rejects_oversize_and_cleans_up(tmp_path):
    up = FakeUpload(b"x" * (2 * 1024 * 1024), filename="big.csv")
    with pytest.raises(HTTPException) as ei:
        await _spool_to_disk(up, limit=1024 * 1024)  # 1 MB cap
    assert ei.value.status_code == 413


def test_upload_limit_is_smaller_for_excel():
    assert _upload_limit("report.xlsx") == _EXCEL_MAX
    assert _upload_limit("report.XLSB") == _EXCEL_MAX  # case-insensitive
    assert _upload_limit("data.csv") == _QUOTA_BYTES


def test_excel_413_message_mentions_csv():
    from app.features.files.router import _too_large_detail
    msg = _too_large_detail("report.xlsx")
    assert "CSV" in msg and "30" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_upload_spool.py -v`
Expected: FAIL — `ImportError: cannot import name '_spool_to_disk'`

- [ ] **Step 3: Implement in router.py**

Replace lines 20-34 of `backend/app/features/files/router.py` (the `_QUOTA_BYTES`/`_CHUNK` constants and the whole `_read_limited` function) with:

```python
import tempfile
from pathlib import Path

_QUOTA_BYTES = 200 * 1024 * 1024  # 200 MB — per-upload cap for streamable formats + total quota
_EXCEL_MAX = 30 * 1024 * 1024     # 30 MB — Excel-family cap: xlsx decompresses to 20-50x in RAM
_CHUNK = 1024 * 1024              # 1 MB read window

# Mirrors service._EXCEL_EXTS — formats that must be fully loaded to parse.
_EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".xltx", ".xltm")


def _upload_limit(filename: str) -> int:
    """Excel-family files get a much lower cap: the format can't be stream-parsed,
    so the whole (compressed!) workbook lands in RAM as a DataFrame."""
    ext = Path(filename or "").suffix.lower()
    return _EXCEL_MAX if ext in _EXCEL_SUFFIXES else _QUOTA_BYTES


def _too_large_detail(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in _EXCEL_SUFFIXES:
        return (
            "Excel file too large (max 30 MB). For big datasets, open the file in "
            "Excel and 'Save As' CSV, then upload the CSV — CSV imports stream "
            "without a size penalty (up to 200 MB)."
        )
    return "File too large (max 200 MB)"


async def _spool_to_disk(file: UploadFile, limit: int) -> Path:
    """Stream the upload to a temp file, never holding more than one chunk in RAM.
    Raises 413 (and removes the partial file) as soon as `limit` is exceeded.
    Caller is responsible for unlinking the returned path when done."""
    total = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".upload")
    try:
        while chunk := await file.read(_CHUNK):
            total += len(chunk)
            if total > limit:
                raise HTTPException(status_code=413, detail=_too_large_detail(file.filename or ""))
            tmp.write(chunk)
    except BaseException:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    tmp.close()
    return Path(tmp.name)
```

Note: `upload()` still calls `_read_limited` at this point — it keeps working because we haven't deleted it yet? No — we replaced it. To keep the app importable and tests green mid-refactor, also update the call site now, minimally (full router rewiring happens in Task 6):

```python
# in upload(), replace:
#   content = await _read_limited(file, _QUOTA_BYTES)
# with:
    tmp_path = await _spool_to_disk(file, _upload_limit(file.filename or ""))
    content = tmp_path.read_bytes()  # TEMPORARY bridge — removed in Task 6
    tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_upload_spool.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/files/router.py backend/tests/test_upload_spool.py
git commit -m "feat(files): spool uploads to disk with 30MB Excel cap"
```

---

### Task 3: Service layer takes `Path` instead of `bytes`

**Files:**
- Modify: `backend/app/features/files/service.py` (signatures: `save_and_import`, `_import_to_project_db`, `_append_to_project_table`, `_save_for_excel`, `_read_tables`, `_read_csv_smart` → `_sniff_csv`, `_read_excel_sheets`, `_to_xlsx_bytes`)
- Test: `backend/tests/test_service_paths.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_paths.py
"""Path-based service API: CSV sniffing reads from disk; _read_tables accepts a
Path; xlsx 'excel' mode copies the temp file instead of loading it."""
from pathlib import Path

import pytest

from app.features.files import service


@pytest.fixture
def csv_file(tmp_path) -> Path:
    p = tmp_path / "sales.csv"
    p.write_bytes(b"name,amount\nalice,100\nbob,200\n")
    return p


@pytest.fixture
def euro_csv(tmp_path) -> Path:
    p = tmp_path / "euro.csv"
    p.write_bytes(b"name;amount\nalice;1.234,56\n")
    return p


def test_sniff_csv_plain(csv_file):
    kw = service._sniff_csv(csv_file, ".csv")
    assert kw["sep"] == "," and kw["decimal"] == "."


def test_sniff_csv_european(euro_csv):
    kw = service._sniff_csv(euro_csv, ".csv")
    assert kw["sep"] == ";" and kw["decimal"] == "," and kw["thousands"] == "."


def test_read_tables_csv_from_path(csv_file):
    tables = service._read_tables(".csv", csv_file)
    df = tables[None]
    assert list(df.columns) == ["name", "amount"]
    assert len(df) == 2


def test_read_tables_txt_not_delimited(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"just some plain prose without delimiters\n")
    with pytest.raises(service.FileImportError):
        service._read_tables(".txt", p)


async def test_save_for_excel_xlsx_is_copied_not_parsed(tmp_path, monkeypatch):
    # A corrupt xlsx must still be accepted in 'excel' mode: native .xlsx is
    # stored as-is (never parsed), so only a copy happens.
    src = tmp_path / "book.xlsx"
    src.write_bytes(b"PK\x03\x04 not really a workbook")

    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {"data_root": str(tmp_path / "data")})())

    async def fake_insert(user_id, session_id, name, disk_path, size):
        return {"id": "f1", "filename": name, "size_bytes": size, "created_at": None}
    monkeypatch.setattr(service.repo, "insert_file", fake_insert)

    rec = await service._save_for_excel("u1", "s1", "book.xlsx", src)
    stored = tmp_path / "data" / "uploads" / "s1" / "book.xlsx"
    assert stored.exists() and stored.read_bytes() == src.read_bytes()
    assert rec["size_bytes"] == src.stat().st_size
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_service_paths.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_sniff_csv'` / signature mismatches

- [ ] **Step 3: Implement — replace `_read_csv_smart` with `_sniff_csv` + path-based readers**

In `backend/app/features/files/service.py`, replace `_read_csv_smart` (lines 94-120) with:

```python
_SNIFF_BYTES = 65536  # sniff encoding/delimiter/decimal from the first 64 KB only


def _sniff_csv(path: Path, ext: str) -> dict:
    """Detect encoding + delimiter + decimal style from the head of the file and
    return kwargs for pd.read_csv. Sniffing a 64 KB sample keeps RAM flat no
    matter how large the file is."""
    with path.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)

    if head.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "latin-1"
        for enc in ("utf-8", "cp1258", "latin-1"):
            try:
                head.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue

    sample = head[:8192].decode(encoding, errors="replace")
    if ext == ".txt" and not any(d in sample for d in (",", ";", "\t")):
        raise FileImportError("Text file is not delimited — cannot import as a table")
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        sep = "\t" if ext == ".tsv" else ","

    decimal = "," if sep == ";" and _looks_european(sample) else "."
    thousands = "." if decimal == "," else ","
    return {"sep": sep, "encoding": encoding, "decimal": decimal, "thousands": thousands}


def _read_csv_full(path: Path, ext: str):
    """Whole-file CSV read (small files / xlsx conversion). Streaming imports use
    _sniff_csv + pd.read_csv(chunksize=...) directly — see _import_csv_streaming."""
    import pandas as pd  # lazy

    return pd.read_csv(path, **_sniff_csv(path, ext))
```

- [ ] **Step 4: Implement — path-based `_read_excel_sheets`, `_read_tables`, `_to_xlsx_bytes`**

```python
def _read_excel_sheets(path: Path) -> dict:
    """All sheets as {name: df}. calamine first (xlsx/xls/xlsb/ods), then pandas default.
    NOTE: loads the whole workbook — callers must enforce the Excel size cap first."""
    import pandas as pd  # lazy

    last_err: Exception | None = None
    for engine in ("calamine", None):
        try:
            kwargs: dict = {"sheet_name": None}
            if engine:
                kwargs["engine"] = engine
            return pd.read_excel(path, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("excel read (engine=%s) failed: %s", engine, e)
    raise FileImportError(f"Could not read spreadsheet ({last_err})")


def _read_tables(ext: str, path: Path) -> dict:
    """Parse a tabular FILE into {sheet_label_or_None: DataFrame}. Same contract as
    before, but reads from disk instead of a bytes blob."""
    if ext in _DELIMITED_EXTS:
        return {None: _sanitize_columns(_read_csv_full(path, ext))}
    if ext in _EXCEL_EXTS:
        sheets = _read_excel_sheets(path)
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


def _to_xlsx_bytes(ext: str, path: Path) -> bytes:
    """Convert a tabular file to .xlsx bytes so the (xlsx-only) excel-server can read it.
    Delimited → one sheet; Excel-family → every sheet preserved (formulas are not).

    Written via openpyxl directly rather than pandas' ExcelWriter, which is broken on
    pandas 3.0 + openpyxl 3.1 ("At least one sheet must be visible")."""
    from openpyxl import Workbook
    from openpyxl.utils.dataframe import dataframe_to_rows

    if ext in _DELIMITED_EXTS:
        sheets = {"Sheet1": _read_csv_full(path, ext)}
    else:
        sheets = _read_excel_sheets(path)

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
```

Remove the old `BytesIO` import if no longer used elsewhere in the module (it still is, in `_to_xlsx_bytes`'s `out = BytesIO()` — keep it).

- [ ] **Step 5: Implement — `save_and_import` chain takes `path: Path`**

```python
async def save_and_import(
    user_id: str,
    session_id: str,
    filename: str,
    path: Path,                       # ← was content: bytes
    *,
    mode: str,
    project_id: str | None = None,
    project_db_url: str | None = None,
    target_table: str | None = None,
) -> dict:
    logger.info(
        "→ save_and_import(user_id=%r session_id=%r filename=%r mode=%r project_id=%r target_table=%r size=%d)",
        user_id, session_id, filename, mode, project_id, target_table, path.stat().st_size,
    )
    if mode == "project_db":
        if target_table:
            return await _append_to_project_table(filename, path, project_id, project_db_url, target_table)
        return await _import_to_project_db(filename, path, project_id, project_db_url)
    if mode == "excel":
        return await _save_for_excel(user_id, session_id, filename, path)
    raise FileImportError(f"Unknown import mode: {mode!r}")
```

`_import_to_project_db` / `_append_to_project_table`: change parameter `content: bytes` → `path: Path`; every `_read_tables(ext, content)` → `await asyncio.to_thread(_read_tables, ext, path)` (the to_thread wrap is Task 5's test target but apply it now); every `len(content)` → `path.stat().st_size`.

`_save_for_excel`: native `.xlsx` becomes a **file copy** (no bytes in RAM); conversions stay whole-load (already capped at 30 MB by the router):

```python
async def _save_for_excel(user_id: str, session_id: str, filename: str, path: Path) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in _EXCEL_EDITABLE:
        raise FileImportError("This file type can't be opened as an Excel workbook")
    out_name = _safe_filename(filename, suffix=".xlsx")
    uploads = (Path(get_settings().data_root) / "uploads" / session_id).resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    disk_path = (uploads / out_name).resolve()
    if uploads not in disk_path.parents:
        raise FileImportError("Invalid file name")
    if ext == ".xlsx":
        await asyncio.to_thread(shutil.copyfile, path, disk_path)  # stored as-is, never parsed
    else:
        out_bytes = await asyncio.to_thread(_to_xlsx_bytes, ext, path)
        disk_path.write_bytes(out_bytes)
    return await repo.insert_file(user_id, session_id, out_name, str(disk_path), disk_path.stat().st_size)
```

Add `import shutil` to the module imports.

- [ ] **Step 6: Update the router call site (keep the Task 2 bridge working)**

In `upload()` in router.py, delete the temporary `content = tmp_path.read_bytes()` bridge; pass the path (full wiring incl. cleanup lands in Task 6):

```python
    tmp_path = await _spool_to_disk(file, _upload_limit(file.filename or ""))
    ...
    rec = await service.save_and_import(
        user_id, session_id, file.filename or "upload", tmp_path,
        mode=import_mode, project_id=pid, project_db_url=project_db_url,
        target_table=(target_table or None),
    )
```

The quota check `used + len(content)` becomes `used + tmp_path.stat().st_size`.

- [ ] **Step 7: Run the whole suite**

Run: `cd backend && uv run pytest tests/ -v`
Expected: all tests pass (Task 2's + Task 3's)

- [ ] **Step 8: Commit**

```bash
git add backend/app/features/files/service.py backend/app/features/files/router.py backend/tests/test_service_paths.py
git commit -m "refactor(files): service layer reads uploads from disk paths, not RAM blobs"
```

---

### Task 4: Streaming CSV import (`chunksize` → per-chunk append)

**Files:**
- Modify: `backend/app/features/files/service.py` (`_import_to_project_db` gains a CSV fast path; new `_import_csv_streaming`; `_append_to_project_table` gains the same for CSV)
- Test: `backend/tests/test_csv_streaming.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_csv_streaming.py
"""Streaming import: N chunks → 1 create + N-1 appends; mid-stream failure drops
the half-written table; column sanitization is consistent across chunks."""
from pathlib import Path

import pytest

from app.features.files import service
from tests.conftest import FakeAdapter


@pytest.fixture
def big_csv(tmp_path) -> Path:
    p = tmp_path / "big.csv"
    rows = "\n".join(f"r{i},{i}" for i in range(250))
    p.write_text(f"name,name\n{rows}\n")  # duplicate header → sanitizer must dedupe
    return p


async def test_streams_in_chunks(big_csv, fake_adapter, monkeypatch):
    monkeypatch.setattr(service, "_CSV_CHUNK_ROWS", 100)
    rec = await service._import_csv_streaming("big.csv", big_csv, ".csv", fake_adapter)
    # 250 rows / 100 per chunk = 3 calls: fail (create), append, append
    assert [c[2] for c in fake_adapter.calls] == ["fail", "append", "append"]
    assert sum(c[1] for c in fake_adapter.calls) == 250
    assert fake_adapter.calls[0][0] == "big"
    # duplicate 'name' header sanitized identically in every chunk
    assert rec["tables"][0]["columns"] == ["name", "name_1"]


async def test_midstream_failure_drops_table(big_csv, fake_adapter, monkeypatch):
    monkeypatch.setattr(service, "_CSV_CHUNK_ROWS", 100)
    fake_adapter.fail_on_call = 2  # first append blows up
    with pytest.raises(service.FileImportError):
        await service._import_csv_streaming("big.csv", big_csv, ".csv", fake_adapter)
    assert any("big" in d for d in fake_adapter.dropped)


async def test_clash_refused_before_any_write(big_csv):
    adapter = FakeAdapter(schema={"big": []})
    with pytest.raises(service.FileImportError, match="already exists"):
        await service._import_csv_streaming("big.csv", big_csv, ".csv", adapter)
    assert adapter.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_csv_streaming.py -v`
Expected: FAIL — `AttributeError: ... no attribute '_import_csv_streaming'`

- [ ] **Step 3: Implement `_import_csv_streaming`**

Add to `service.py` (below `_import_to_project_db`):

```python
_CSV_CHUNK_ROWS = 50_000  # ~50k rows per DB round-trip keeps peak RAM at tens of MB


async def _import_csv_streaming(filename: str, path: Path, ext: str, adapter) -> dict:
    """Stream a delimited file into a NEW project table without ever loading the
    whole file: pandas reads `_CSV_CHUNK_ROWS` at a time (in a worker thread so the
    event loop stays free) and each chunk is appended to the table. On a mid-stream
    failure the half-written table is dropped — no partial imports survive."""
    import pandas as pd  # lazy

    table = _project_table_name(filename)
    if table in set((await adapter.get_schema()).keys()):
        raise FileImportError(
            f"Table already exists in the database: {table}. "
            "Rename the file or drop the existing table first."
        )

    kwargs = _sniff_csv(path, ext)
    reader = pd.read_csv(path, chunksize=_CSV_CHUNK_ROWS, **kwargs)

    def _next_chunk():
        try:
            return next(reader)
        except StopIteration:
            return None

    columns: list[str] = []
    total_rows = 0
    if_exists = "fail"  # first chunk creates the table; ValueError = lost a creation race
    try:
        while (chunk := await asyncio.to_thread(_next_chunk)) is not None:
            df = _sanitize_columns(chunk)  # same headers every chunk → same names
            if not columns:
                columns = [str(c) for c in df.columns]
            try:
                await adapter.import_dataframe(table, df, if_exists=if_exists)
            except ValueError as e:
                raise FileImportError(f"Table '{table}' already exists.") from e
            if_exists = "append"
            total_rows += len(df)
    except FileImportError:
        raise
    except Exception as e:  # noqa: BLE001 — clean up the partial table, surface a clean reason
        if total_rows or if_exists == "append":
            try:
                await adapter.execute(f'DROP TABLE IF EXISTS "{table}"')
            except Exception:  # noqa: BLE001
                logger.warning("could not drop partial table %s", table)
        raise FileImportError(f"Import failed after {total_rows} rows: {e}") from e
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()

    if total_rows == 0 and not columns:
        raise FileImportError("File contains no rows")
    return {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "size_bytes": path.stat().st_size,
        "created_at": None,
        "tables": [{"name": table, "columns": columns}],
    }
```

Wait — `test_midstream_failure_drops_table` expects a drop after the FIRST append fails (`total_rows` is already >0 from the create call). The condition `if total_rows or if_exists == "append"` covers it: after the create succeeded, `if_exists` is "append". Correct as written.

- [ ] **Step 4: Route CSV through the streaming path in `_import_to_project_db`**

```python
async def _import_to_project_db(
    filename: str, path: Path, project_id: str | None, project_db_url: str | None
) -> dict:
    if not (project_id and project_db_url):
        raise FileImportError("No project database to import into")
    ext = Path(filename).suffix.lower()
    if ext not in _TABULAR_EXTS:
        raise FileImportError("Only CSV/Excel files can be imported into the database")

    from app.agent.pool import get_connection_pool
    adapter = await get_connection_pool().adapter_for(project_id, project_db_url)

    if ext in _DELIMITED_EXTS:  # CSV/TSV/TXT stream — flat RAM at any size
        return await _import_csv_streaming(filename, path, ext, adapter)

    # Excel-family: whole-workbook load (router caps these at 30 MB), off the event loop.
    tables = await asyncio.to_thread(_read_tables, ext, path)
    # Project tables keep a clean, file-derived name (no t_). Refuse to clobber an existing
    # table — the user must rename the file or drop the table first (no silent overwrite).
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
        "size_bytes": path.stat().st_size,
        "created_at": None,
        # New project tables → the FE offers a "describe this table" step (data dictionary).
        "tables": created,
    }
```

Also in `_append_to_project_table`: for `ext in _DELIMITED_EXTS`, read chunked with the same `_sniff_csv` kwargs and run `_align_to_table` per chunk (alignment only needs column names, identical each chunk):

```python
    if ext in _DELIMITED_EXTS:
        import pandas as pd
        reader = pd.read_csv(path, chunksize=_CSV_CHUNK_ROWS, **_sniff_csv(path, ext))

        def _next_chunk():
            try:
                return next(reader)
            except StopIteration:
                return None

        checked = False
        try:
            while (chunk := await asyncio.to_thread(_next_chunk)) is not None:
                aligned, missing_required = _align_to_table(_sanitize_columns(chunk), schema[target_table])
                if not checked:  # validate once, on first-chunk columns
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
                    checked = True
                await adapter.import_dataframe(target_table, aligned, if_exists="append")
        except FileImportError:
            raise
        except Exception as e:  # noqa: BLE001
            from app.agent.graph import dbtools
            raise FileImportError(
                f"Couldn’t append to '{target_table}': {dbtools.clean_db_error(str(e))}."
            ) from e
        finally:
            close = getattr(reader, "close", None)
            if close:
                close()
        return {"id": str(uuid.uuid4()), "filename": filename,
                "size_bytes": path.stat().st_size, "created_at": None}
```

(The multi-sheet guard stays for the Excel branch only — a CSV is single-table by definition. Excel appends keep the existing whole-load path, wrapped in `asyncio.to_thread(_read_tables, ext, path)`.)

NOTE: appends are NOT rolled back on mid-stream failure (the table pre-existed with real data — dropping it would be worse). Partial appended rows may remain; the error message says how many-ish via the driver error. This matches the current single-shot behavior semantics closely enough.

- [ ] **Step 5: Run the whole suite**

Run: `cd backend && uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/features/files/service.py backend/tests/test_csv_streaming.py
git commit -m "feat(files): stream CSV imports in 50k-row chunks with partial-table cleanup"
```

---### Task 5: Keep the event loop free (to_thread everywhere pandas runs)

**Files:**
- Modify: `backend/app/features/files/service.py` (audit — most wraps landed in Tasks 3-4)
- Test: `backend/tests/test_service_paths.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_service_paths.py`:

```python
async def test_no_sync_read_tables_call_in_import_paths():
    """_read_tables blocks for seconds on big files — every call in async import
    paths must go through asyncio.to_thread. Guard against regression by source
    inspection (cheap and honest: the behavioral difference needs a 100MB file)."""
    import inspect
    src = inspect.getsource(service)
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "def _read_tables" in stripped:
            continue
        if "_read_tables(" in stripped and "to_thread" not in stripped:
            raise AssertionError(f"sync _read_tables call found: {stripped}")
```

- [ ] **Step 2: Run to verify current state**

Run: `cd backend && uv run pytest tests/test_service_paths.py -v`
Expected: PASS if Tasks 3-4 wrapped every call site; FAIL pointing at any missed line. Fix any hit by wrapping with `await asyncio.to_thread(_read_tables, ext, path)`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/features/files/service.py backend/tests/test_service_paths.py
git commit -m "test(files): guard that pandas parsing never blocks the event loop"
```

---

### Task 6: Router final wiring — quota by file size, guaranteed temp cleanup

**Files:**
- Modify: `backend/app/features/files/router.py` (`upload()` body)

- [ ] **Step 1: Rewrite `upload()`'s body after the mode/session checks**

```python
    tmp_path = await _spool_to_disk(file, _upload_limit(file.filename or ""))
    try:
        size = tmp_path.stat().st_size

        # Cumulative quota: per-file size was capped above; also reject when the user's
        # TOTAL stored bytes would exceed the limit. Only 'excel' persists into `files`.
        if import_mode == "excel":
            used, _ = await repo.user_storage(user_id)
            if used + size > _QUOTA_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Storage quota exceeded (200 MB total). Delete some files first.",
                )

        # project_db needs the project's resolved DSN (ownership-checked); other modes don't.
        project_db_url: str | None = None
        pid = project_id or sess.get("project_id")
        if import_mode == "project_db":
            me = await auth_repo.get_user(user_id)
            if (me or {}).get("role") == "viewer":
                raise HTTPException(
                    status_code=403,
                    detail="Viewers can edit Excel files, but can't import data into the database.",
                )
            if not pid:
                raise HTTPException(status_code=400, detail="No project to import into")
            project_db_url = await proj_service.resolve_db_url(pid, user_id)
            if not project_db_url:
                raise HTTPException(status_code=400, detail="Project has no database connected")

        try:
            rec = await service.save_and_import(
                user_id, session_id, file.filename or "upload", tmp_path,
                mode=import_mode, project_id=pid, project_db_url=project_db_url,
                target_table=(target_table or None),
            )
        except service.FileImportError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)  # temp upload never outlives the request

    resp: dict = {"file": _meta(rec)}
    if rec.get("tables"):
        resp["tables"] = rec["tables"]
    return resp
```

- [ ] **Step 2: Full suite + import smoke**

Run: `cd backend && uv run pytest tests/ -v && uv run python -c "from app.features.files import router, service; print('imports OK')"`
Expected: all pass, "imports OK"

- [ ] **Step 3: Commit**

```bash
git add backend/app/features/files/router.py
git commit -m "feat(files): wire streaming upload end-to-end with guaranteed temp cleanup"
```

---

### Task 7: End-to-end verification

- [ ] **Step 1: Generate test files and smoke-test locally**

```bash
cd backend
# 120 MB CSV (over the old RAM-killer size, well under the 200 MB cap)
uv run python - <<'EOF'
import csv, random
with open("/tmp/big_test.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "name", "amount", "note"])
    for i in range(1_600_000):
        w.writerow([i, f"user_{i}", random.random() * 1000, "x" * 40])
EOF
ls -lh /tmp/big_test.csv   # expect ~120M
# 35 MB fake xlsx (over the 30 MB Excel cap) — content irrelevant, size is what's tested
head -c 36700160 /dev/urandom > /tmp/too_big.xlsx
```

- [ ] **Step 2: Run the API locally and exercise both paths**

Start the stack (per `backend/README.md` / `Makefile` — e.g. `make dev` or `docker compose up`), grab a session cookie from the browser, then:

```bash
# CSV 120 MB → expect 200 + tables in response; watch RSS stay flat:
watch -n1 'ps -o rss= -p $(pgrep -f uvicorn) | awk "{print \$1/1024 \" MB\"}"' &
curl -s -X POST http://127.0.0.1:5001/api/files/upload \
  -H "Cookie: $COOKIE" \
  -F session_id=$SESSION -F import_mode=project_db -F project_id=$PROJECT \
  -F file=@/tmp/big_test.csv | head -c 400

# Oversized xlsx → expect HTTP 413 with the "Save As CSV" hint:
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5001/api/files/upload \
  -H "Cookie: $COOKIE" \
  -F session_id=$SESSION -F import_mode=project_db -F project_id=$PROJECT \
  -F file=@/tmp/too_big.xlsx
```

Expected: CSV import succeeds with worker RSS staying under ~300 MB throughout; xlsx returns 413 immediately (aborts at the 30 MB boundary, before the upload finishes).

- [ ] **Step 3: Check no temp files leak**

Run: `ls /tmp/*.upload 2>/dev/null | wc -l`
Expected: 0

- [ ] **Step 4: Commit any fixes, then final commit**

```bash
git add -A backend
git commit -m "fix(files): stream uploads to disk — no more OOM on large imports"
```

---

## Deployment notes (EC2, not part of the code plan)

- Add 4 GB swap as a safety net (instance survives any residual spike):
  `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab`
- nginx `client_max_body_size 200m` already matches the CSV cap — no change needed.
- Frontend (`frontend/nginx.conf`) has `client_max_body_size 50M` — raise to `200M` if any deployment routes uploads through it (the production FE calls `api.dbeelight.io.vn` directly, so this only matters for docker-compose local).
- `server_tokens build;` in `/etc/nginx/nginx.conf` leaks the nginx version — change to `server_tokens off;`.
- FE (`frontend/src`): surface the new 413 detail string to the user (it now explains the Save-As-CSV workaround). Check the upload error handler displays `detail` from the response body.
