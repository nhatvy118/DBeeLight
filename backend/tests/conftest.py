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
