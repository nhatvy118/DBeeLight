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
    # duplicate 'name' header deduped by pandas (mangle) identically in every chunk —
    # same behavior as the old whole-file path
    assert rec["tables"][0]["columns"] == ["name", "name.1"]


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
