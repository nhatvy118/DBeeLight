"""Upload a file → save to the shared volume + import the table into the session SQLite (t_ prefix).

The imported table is queried by the agent via the session adapter (DbContext.session). The original
.xlsx lives on the shared volume so the excel-server (HTTP) can read it.
"""
from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path

from app.config import get_settings
from app.features.files import repository as repo

logger = logging.getLogger("files")


def _table_name(filename: str) -> str:
    stem = Path(filename).stem.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "data"
    return f"t_{slug}"


def _session_sqlite_path(session_id: str) -> Path:
    return get_settings().temp_dbs_dir / f"{session_id}.sqlite"


async def save_and_import(user_id: str, session_id: str, filename: str, content: bytes) -> dict:
    s = get_settings()
    uploads = Path(s.data_root) / "uploads" / session_id
    uploads.mkdir(parents=True, exist_ok=True)
    disk_path = uploads / filename
    disk_path.write_bytes(content)

    table_name: str | None = None
    sqlite_path: str | None = None
    ext = Path(filename).suffix.lower()

    if ext in (".csv", ".xlsx", ".xls"):
        import pandas as pd  # lazy: the app still boots when pandas is not installed

        if ext == ".csv":
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content))
        table_name = _table_name(filename)
        spath = _session_sqlite_path(session_id)
        # write via sync sqlite3 in a threadpool to avoid blocking the event loop
        import asyncio
        import sqlite3

        def _write():
            con = sqlite3.connect(str(spath))
            try:
                df.to_sql(table_name, con, if_exists="replace", index=False)
            finally:
                con.close()

        await asyncio.to_thread(_write)
        sqlite_path = str(spath)

    return await repo.insert_file(
        user_id, session_id, filename, str(disk_path), sqlite_path, table_name, len(content)
    )


async def session_db(session_id: str) -> tuple[str | None, frozenset[str] | None]:
    """(session SQLite path, allowed table set) — used to attach the session adapter."""
    files = await repo.list_for_session(session_id)
    path = None
    tables: set[str] = set()
    for f in files:
        if f.get("sqlite_db_path") and f.get("table_name"):
            path = f["sqlite_db_path"]
            tables.add(f["table_name"])
    return path, (frozenset(tables) if tables else None)
