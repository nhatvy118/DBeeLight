"""Unit tests for RAG context formatting (no DB required).

Import the module by path so ``internal/__init__.py`` (FastAPI stack) is not loaded.
"""

import importlib.util
import sys
from pathlib import Path

_rs_path = Path(__file__).resolve().parents[1] / "internal/services/retrieval_service.py"
_spec = importlib.util.spec_from_file_location("retrieval_service_standalone", _rs_path)
_rs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["retrieval_service_standalone"] = _rs
_spec.loader.exec_module(_rs)
ChunkResult = _rs.ChunkResult
format_chunks_as_context_block = _rs.format_chunks_as_context_block


def test_format_chunks_empty():
    assert format_chunks_as_context_block([]) == ""


def test_format_chunks_basic_structure():
    chunks = [
        ChunkResult(
            chunk_text="col1\tcol2\na\tb",
            metadata={"filename": "t.csv", "kind": "window", "sheet": "Sheet1"},
            distance=0.1,
        )
    ]
    out = format_chunks_as_context_block(chunks)
    assert "[ATTACHED FILES CONTEXT]" in out
    assert "<file:t.csv | Sheet1 | window>" in out
    assert "col1\tcol2" in out


def test_format_chunks_truncates_when_huge():
    """Very long chunk text should trigger truncation path."""
    huge = "x" * 200_000
    chunks = [
        ChunkResult(
            chunk_text=huge,
            metadata={"filename": "big.txt", "kind": "text"},
            distance=0.05,
        )
    ]
    out = format_chunks_as_context_block(chunks)
    assert len(out) < len(huge) + 500
    assert "truncated" in out.lower()


def test_format_chunks_includes_available_sqlite_tables():
    chunks = [
        ChunkResult(
            chunk_text="col1\tcol2\na\tb",
            metadata={"filename": "t.csv", "kind": "window", "sheet": "Sheet1"},
            distance=0.1,
        )
    ]
    tables = [
        {
            "filename": "user_accounts.xlsx",
            "sheet": "Sheet1",
            "sqlite_table_name": "t_50_user_accounts_Sheet1_abcd1234",
            "columns": ["id", "name", "email"],
        }
    ]
    out = format_chunks_as_context_block(chunks, tables)
    assert "AVAILABLE SQLITE TABLES" in out
    assert "`t_50_user_accounts_Sheet1_abcd1234`" in out
    assert "id, name, email" in out


def test_format_chunks_tables_only_no_vector_hits():
    out = format_chunks_as_context_block(
        [],
        [
            {
                "filename": "x.csv",
                "sheet": "",
                "sqlite_table_name": "t_x_sheet_fff",
                "columns": ["a"],
            }
        ],
    )
    assert "[ATTACHED FILES CONTEXT]" in out
    assert "AVAILABLE SQLITE TABLES" in out
    assert "No indexed excerpts matched" in out
