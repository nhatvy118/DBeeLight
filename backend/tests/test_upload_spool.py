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
