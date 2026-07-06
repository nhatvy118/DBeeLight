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

    monkeypatch.setattr(
        service, "get_settings",
        lambda: type("S", (), {"data_root": str(tmp_path / "data")})(),
    )

    async def fake_insert(user_id, session_id, name, disk_path, size):
        return {"id": "f1", "filename": name, "size_bytes": size, "created_at": None}

    monkeypatch.setattr(service.repo, "insert_file", fake_insert)

    rec = await service._save_for_excel("u1", "s1", "book.xlsx", src)
    stored = tmp_path / "data" / "uploads" / "s1" / "book.xlsx"
    assert stored.exists() and stored.read_bytes() == src.read_bytes()
    assert rec["size_bytes"] == src.stat().st_size


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
