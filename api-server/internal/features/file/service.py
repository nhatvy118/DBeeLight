"""Upload, import to SQLite, and cleanup session-attached files."""

from __future__ import annotations

import asyncio
import base64
import csv
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import asyncpg
from fastapi import HTTPException, UploadFile

from internal.features.file.repository import FileRepository
from internal.features.project.repository import ProjectRepository
from internal.features.file.services.file_parse_service import (
    parse_file,
    suggested_sqlite_table_names,
)
from internal.features.file.schema_context import (
    fetch_table_schema_entry,
    format_session_schema_block,
    normalize_schema_snapshot,
)
logger = logging.getLogger(__name__)

# Indexed session files (``/api/files/upload``) — total stored bytes per user.
USER_STORAGE_LIMIT_BYTES = 5 * 1024 * 1024 * 1024

# Session files (upload import + chat export) under ``file_handle/{user}/{session_id}/import|export/``.
SESSION_IMPORT_SUBDIR = "import"
SESSION_EXPORT_SUBDIR = "export"


def _file_handle_root() -> Path:
    return _internal_data_root() / "file_handle"


def _session_file_tree_dir(user_key: str, session_id: str) -> Path:
    return _file_handle_root() / user_key / session_id


def _path_parts(local_path: str) -> tuple[str, ...]:
    try:
        return Path(local_path).expanduser().resolve().parts
    except OSError:
        return ()


def _path_is_file_handle_subdir(parts: tuple[str, ...], user_key: str, subdir: str) -> bool:
    try:
        i = parts.index("file_handle")
    except ValueError:
        return False
    if len(parts) < i + 5:
        return False
    return parts[i + 1] == user_key and parts[i + 3] == subdir


def classify_session_stored_path(local_path: str, user_key: str) -> str:
    """``import`` (session upload), ``chat_export`` (assistant Excel), or ``other``."""
    parts = _path_parts(local_path)
    if not parts:
        return "other"
    if _path_is_file_handle_subdir(parts, user_key, SESSION_EXPORT_SUBDIR):
        return "chat_export"
    if _path_is_file_handle_subdir(parts, user_key, SESSION_IMPORT_SUBDIR):
        return "import"
    return "other"


# Session file markers from the chat UI (``frontend/src/utils/sessionFileMarkers.ts``).
_SESSION_FILE_PAIR_RE = re.compile(
    r"\[SESSION_FILE_ID_START\](?P<fid>[\s\S]*?)\[SESSION_FILE_ID_END\]\s*\n?\s*"
    r"\[UPLOADED_EXCEL_NAME_START\](?P<fname>[\s\S]*?)\[UPLOADED_EXCEL_NAME_END\]"
)

# Assistant Excel export markers (see ``frontend/src/utils/excelExportMarkers.ts``).
_ASSIST_EXCEL_B64_RE = re.compile(
    r"\[EXCEL_BASE64_START\](?P<b64>[\s\S]*?)\[EXCEL_BASE64_END\]",
)
_ASSIST_FILENAME_RE = re.compile(
    r"\[FILENAME_START\](?P<fn>[\s\S]*?)\[FILENAME_END\]",
)
_ASSIST_ROW_COUNT_RE = re.compile(
    # Whitespace-tolerant: the LLM may format the number on its own line.
    r"\[ROW_COUNT_START\]\s*(?P<rc>\d+)\s*\[ROW_COUNT_END\]",
)



def _internal_data_root() -> Path:
    """Root for all runtime user data: ``api-server/internal/`` (file_handle,
    temp_dbs, databases live directly under here). parents[2] of
    ``internal/features/file/service.py`` == ``internal/``."""
    return Path(__file__).resolve().parents[2]


def _temp_db_path(session_id: str) -> Path:
    d = _internal_data_root() / "temp_dbs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.db"


def _sqlite_url_from_path(p: Path) -> str:
    s = str(p.resolve())
    return f"sqlite:///{s}" if not s.startswith("/") else f"sqlite:///{s}"


def _sqlite_engine_url_from_stored(stored: str | None) -> str | None:
    """Build SQLAlchemy SQLite URL from ``files.sqlite_db_path`` (URL or filesystem path)."""
    if not stored:
        return None
    s = str(stored).strip()
    if not s:
        return None
    if s.startswith("sqlite:"):
        return s
    return _sqlite_url_from_path(Path(s))


class FileService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        project_repo: Optional[ProjectRepository] = None,
    ):
        self._pool = pool
        self._files = FileRepository(pool)
        self._project_repo = project_repo

    async def _require_session(self, session_id: str, user_id: str) -> dict[str, Any]:
        row = await self._pool.fetchrow(
            "SELECT id, project_id FROM session WHERE id = $1 AND user_id = $2",
            session_id,
            user_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"id": row["id"], "project_id": str(row["project_id"]) if row["project_id"] else None}

    async def _storage_bytes_breakdown(self, user_key: str) -> tuple[int, int]:
        """Indexed ``files`` rows only: ``(import_bytes, chat_export_bytes)`` — 5 GB cap."""
        rows = await self._files.list_file_sizes_paths_for_user(user_key)
        imp = chat = 0
        for r in rows:
            sz = int(r["size_bytes"] or 0)
            if (
                classify_session_stored_path(str(r.get("local_path") or ""), user_key)
                == "chat_export"
            ):
                chat += sz
            else:
                imp += sz
        return imp, chat

    async def get_total_storage_used_bytes(self, user_key: str) -> int:
        """All indexed session files (import + chat export). Excel MCP staging excluded from cap."""
        imp, chat = await self._storage_bytes_breakdown(user_key)
        return imp + chat

    async def get_storage_quota_breakdown(self, user_key: str) -> tuple[int, int, int]:
        """``(import_used_bytes, export_used_bytes, total_used_bytes)`` — indexed storage only."""
        imp, chat = await self._storage_bytes_breakdown(user_key)
        return imp, chat, imp + chat


    async def _prune_session_messages_with_file_id(
        self,
        session_id: str,
        user_key: str,
        file_id: UUID,
    ) -> None:
        marker = f"[SESSION_FILE_ID_START]{file_id}[SESSION_FILE_ID_END]"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT content FROM session WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    session_id,
                    user_key,
                )
                if row is None:
                    return
                data = row["content"]
                if isinstance(data, str):
                    data = json.loads(data)
                if not isinstance(data, dict):
                    return
                messages = list(data.get("messages") or [])
                new_messages = [
                    m
                    for m in messages
                    if marker not in str((m or {}).get("content") or "")
                ]
                if len(new_messages) == len(messages):
                    return
                data["messages"] = new_messages
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                await conn.execute(
                    "UPDATE session SET content = $1::jsonb WHERE id = $2 AND user_id = $3",
                    json.dumps(data, ensure_ascii=False),
                    session_id,
                    user_key,
                )

    async def _prune_session_messages_with_export_file_id(
        self,
        session_id: str,
        user_key: str,
        file_id: UUID,
    ) -> None:
        marker = f"[EXPORT_FILE_ID_START]{file_id}[EXPORT_FILE_ID_END]"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT content FROM session WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    session_id,
                    user_key,
                )
                if row is None:
                    return
                data = row["content"]
                if isinstance(data, str):
                    data = json.loads(data)
                if not isinstance(data, dict):
                    return
                messages = list(data.get("messages") or [])
                new_messages = [
                    m
                    for m in messages
                    if marker not in str((m or {}).get("content") or "")
                ]
                if len(new_messages) == len(messages):
                    return
                data["messages"] = new_messages
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                await conn.execute(
                    "UPDATE session SET content = $1::jsonb WHERE id = $2 AND user_id = $3",
                    json.dumps(data, ensure_ascii=False),
                    session_id,
                    user_key,
                )

    async def upload_file(
        self,
        *,
        session_id: str,
        user_key: str,
        upload: UploadFile,
        project_id_override: str | None = None,
        use_project_db: bool | None = None,
    ) -> dict[str, Any]:
        sess = await self._require_session(session_id, user_key)
        pid = project_id_override or sess.get("project_id")

        # Check quota before writing — use Content-Length header when available,
        # otherwise fall back to reading into memory first then checking.
        content_length = upload.size  # set by FastAPI from Content-Length header
        used_before = await self.get_total_storage_used_bytes(user_key)
        if content_length is not None and used_before + content_length > USER_STORAGE_LIMIT_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "storage_quota_exceeded",
                    "message": "User storage limit reached (5 GB). Delete some uploaded files and try again.",
                    "used_bytes": used_before,
                    "limit_bytes": USER_STORAGE_LIMIT_BYTES,
                    "attempted_bytes": content_length,
                },
            )

        original_name = self._safe_filename(upload.filename or "upload.bin")
        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        dest_dir = _session_file_tree_dir(user_key, session_id) / SESSION_IMPORT_SUBDIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / stored_name

        size_bytes = 0
        with dest_path.open("wb") as f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                f.write(chunk)

        # Re-check with actual size if Content-Length was absent or mismatched.
        if content_length is None and used_before + size_bytes > USER_STORAGE_LIMIT_BYTES:
            dest_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "storage_quota_exceeded",
                    "message": "User storage limit reached (5 GB). Delete some uploaded files and try again.",
                    "used_bytes": used_before,
                    "limit_bytes": USER_STORAGE_LIMIT_BYTES,
                    "attempted_bytes": size_bytes,
                },
            )

        mime = upload.content_type or "application/octet-stream"

        try:
            parsed = parse_file(dest_path, original_name, mime)
        except Exception as e:
            dest_path.unlink(missing_ok=True)
            logger.exception("parse failed")
            raise HTTPException(status_code=400, detail=f"Could not parse file: {e}") from e

        sqlite_table_name: str | None = None
        sqlite_db_path: str | None = None

        if parsed.kind == "tabular":
            engine_url: str | None = None
            temp_fs_path: str | None = None
            eff_pid = pid or sess.get("project_id")
            # use_project_db=True  → always try project DB
            # use_project_db=False → always use temp SQLite (user chose "lưu tạm")
            # use_project_db=None  → legacy: auto-use project DB if available
            if use_project_db is not False and eff_pid and self._project_repo:
                proj = await self._project_repo.get_project_by_id(eff_pid, user_key)
                if proj and proj.get("db_url") and not str(proj["db_url"]).startswith("placeholder"):
                    engine_url = str(proj["db_url"]).strip()
            if not engine_url:
                tp = _temp_db_path(session_id)
                engine_url = _sqlite_url_from_path(tp)
                temp_fs_path = str(tp.resolve())

            sqlite_db_path, sqlite_table_name = await asyncio.to_thread(
                self._import_tabular_sync,
                parsed,
                engine_url,
                temp_fs_path,
            )
            if not sqlite_table_name:
                dest_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=400,
                    detail="Could not import spreadsheet into SQLite for SQL queries.",
                )
        else:
            has_text = any(
                str(p.get("text") or "").strip() for p in (parsed.document_parts or [])
            )
            if not (parsed.summary or "").strip() and not has_text:
                dest_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="No readable content in file")

        file_id = await self._files.insert_file(
            session_id=session_id,
            user_id=user_key,
            filename=original_name,
            local_path=str(dest_path),
            mime_type=mime,
            size_bytes=size_bytes,
            sqlite_table_name=sqlite_table_name,
            sqlite_db_path=sqlite_db_path,
            summary=parsed.summary[:2000] if parsed.summary else None,
        )

        if sqlite_table_name and sqlite_db_path:
            engine_url = _sqlite_engine_url_from_stored(str(sqlite_db_path))
            if engine_url:
                dtypes: dict[str, str] = {}
                sheet = ""
                if parsed.kind == "tabular" and parsed.tabular_sheets:
                    sheet = str(parsed.tabular_sheets[0].get("label") or "")
                    df = parsed.tabular_sheets[0].get("dataframe")
                    if df is not None:
                        for c in df.columns:
                            dtypes[str(c)] = str(df[c].dtype)
                try:
                    snap = await asyncio.to_thread(
                        fetch_table_schema_entry,
                        engine_url=engine_url,
                        table_name=str(sqlite_table_name),
                        filename=original_name,
                        sheet=sheet,
                        dtypes=dtypes,
                    )
                    await self._files.update_schema_snapshot(file_id, user_key, snap)
                except Exception as e:
                    logger.warning("schema_snapshot at upload failed: %s", e)

        return {
            "id": str(file_id),
            "filename": original_name,
            "mime_type": mime,
            "size_bytes": size_bytes,
            "summary": parsed.summary,
            "sqlite_table_name": sqlite_table_name,
            "sqlite_db_path": sqlite_db_path,
        }

    async def persist_session_export_xlsx(
        self,
        *,
        session_id: str,
        user_key: str,
        original_filename: str,
        data: bytes,
    ) -> dict[str, Any]:
        """Write export bytes under ``file_handle/{user}/{session}/export/`` and record metadata."""
        await self._require_session(session_id, user_key)
        original_name = self._safe_filename(original_filename)
        if not original_name.lower().endswith((".xlsx", ".xlsm")):
            if "." not in original_name:
                original_name = f"{original_name}.xlsx"
            else:
                original_name = re.sub(r"\.[^.]+$", ".xlsx", original_name)

        size_bytes = len(data)
        used_before = await self.get_total_storage_used_bytes(user_key)
        if used_before + size_bytes > USER_STORAGE_LIMIT_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "storage_quota_exceeded",
                    "message": "User storage limit reached (5 GB). Delete some uploaded files and try again.",
                    "used_bytes": used_before,
                    "limit_bytes": USER_STORAGE_LIMIT_BYTES,
                    "attempted_bytes": size_bytes,
                },
            )

        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        dest_dir = _session_file_tree_dir(user_key, session_id) / SESSION_EXPORT_SUBDIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / stored_name
        dest_path.write_bytes(data)

        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        file_id = await self._files.insert_file(
            session_id=session_id,
            user_id=user_key,
            filename=original_name,
            local_path=str(dest_path),
            mime_type=mime,
            size_bytes=size_bytes,
            sqlite_table_name=None,
            sqlite_db_path=None,
            summary=None,
        )

        return {
            "id": str(file_id),
            "filename": original_name,
            "mime_type": mime,
            "size_bytes": size_bytes,
        }

    async def rewrite_assistant_text_persist_excel_export(
        self,
        text: str,
        *,
        session_id: str,
        user_key: str,
    ) -> str:
        """Replace inline Excel base64 markers with ``[EXPORT_FILE_ID_*]`` after persisting to disk."""
        if not text or "[EXCEL_BASE64_START]" not in text:
            return text
        m_b64 = _ASSIST_EXCEL_B64_RE.search(text)
        if not m_b64:
            return text
        tail = text[m_b64.end() :]
        m_fn = _ASSIST_FILENAME_RE.search(tail)
        if not m_fn:
            return text
        raw_b64 = (m_b64.group("b64") or "").strip()
        fn = self._safe_filename((m_fn.group("fn") or "").strip() or "export.xlsx")
        try:
            blob = base64.b64decode(raw_b64, validate=True)
        except Exception:
            try:
                blob = base64.b64decode(raw_b64)
            except Exception as e:
                logger.warning("assistant export base64 decode failed: %s", e)
                return text
        if not blob:
            return text

        meta = await self.persist_session_export_xlsx(
            session_id=session_id,
            user_key=user_key,
            original_filename=fn,
            data=blob,
        )
        fid = meta["id"]
        fn = str(meta.get("filename") or fn)
        after_fn = tail[m_fn.end() :]
        m_rc = _ASSIST_ROW_COUNT_RE.search(after_fn)
        rc = m_rc.group("rc") if m_rc else "0"

        replacement = (
            f"[EXPORT_FILE_ID_START]{fid}[EXPORT_FILE_ID_END]\n"
            f"[FILENAME_START]{fn}[FILENAME_END]\n"
            f"[ROW_COUNT_START]{rc}[ROW_COUNT_END]"
        )
        end = m_b64.end() + m_fn.end() + (m_rc.end() if m_rc else 0)
        return text[: m_b64.start()].rstrip() + "\n" + replacement + text[end:].lstrip()

    def _import_tabular_sync(
        self,
        parsed,
        engine_url: str,
        temp_fs_path: str | None,
    ) -> tuple[str | None, str | None]:
        try:
            from sqlalchemy import create_engine
        except ImportError as e:
            raise RuntimeError("sqlalchemy required") from e

        engine = create_engine(engine_url)
        short = uuid.uuid4().hex[:8]
        pairs = suggested_sqlite_table_names(parsed)
        primary_table: str | None = None
        for sheet, (_label, suggested) in zip(parsed.tabular_sheets, pairs, strict=False):
            df = sheet["dataframe"].copy()
            if "__row_id" not in df.columns:
                df.insert(0, "__row_id", range(1, len(df) + 1))
            tname = f"{suggested}_{short}"[:63]
            try:
                df.to_sql(tname, engine, if_exists="fail", index=False)
            except ValueError:
                tname = f"{tname}_{uuid.uuid4().hex[:4]}"
                df.to_sql(tname, engine, if_exists="fail", index=False)
            if primary_table is None:
                primary_table = tname
        engine.dispose()
        # Store URL or temp file path so we can reconnect for DROP TABLE
        stored = temp_fs_path if temp_fs_path else engine_url
        return (stored, primary_table)

    @staticmethod
    def _safe_filename(name: str) -> str:
        base = (name or "").strip().split("/")[-1].split("\\")[-1]
        base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip()
        return base or "upload.bin"

    async def list_user_files_inventory(self, user_key: str) -> list[dict[str, Any]]:
        rows = await self._files.list_files_for_user_inventory(user_key, limit=1000)
        out: list[dict[str, Any]] = []
        for r in rows:
            lp = str(r.get("local_path") or "")
            if classify_session_stored_path(lp, user_key) == "chat_export":
                continue
            ts = r.get("uploaded_at")
            out.append(
                {
                    "id": str(r["id"]),
                    "session_id": r["session_id"],
                    "filename": r["filename"],
                    "size_bytes": int(r["size_bytes"] or 0),
                    "uploaded_at": ts.isoformat() if ts else None,
                }
            )
        return out

    async def list_chat_export_files_inventory(self, user_key: str) -> list[dict[str, Any]]:
        """Persisted assistant Excel exports under ``file_handle/.../export/``."""
        rows = await self._files.list_files_for_user_inventory(user_key, limit=1000)
        out: list[dict[str, Any]] = []
        for r in rows:
            lp = str(r.get("local_path") or "")
            if classify_session_stored_path(lp, user_key) != "chat_export":
                continue
            ts = r.get("uploaded_at")
            out.append(
                {
                    "id": str(r["id"]),
                    "session_id": r["session_id"],
                    "filename": r["filename"],
                    "size_bytes": int(r["size_bytes"] or 0),
                    "uploaded_at": ts.isoformat() if ts else None,
                }
            )
        return out

    async def get_file(self, file_id: UUID, user_key: str) -> dict[str, Any] | None:
        """Return raw file row (includes sqlite_table_name, sqlite_db_path, etc.)."""
        return await self._files.get_file(file_id, user_key)

    async def get_file_for_download(self, file_id: UUID, user_key: str) -> dict[str, Any]:
        row = await self._files.get_file(file_id, user_key)
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        lp = str(row.get("local_path") or "").strip()
        if not lp:
            raise HTTPException(status_code=404, detail="File not found")
        path = Path(lp)
        return {
            "path": path,
            "filename": str(row.get("filename") or path.name or "download.bin"),
            "mime_type": row.get("mime_type"),
        }

    async def get_session_files(self, session_id: str, user_key: str) -> list[dict[str, Any]]:
        await self._require_session(session_id, user_key)
        rows = await self._files.list_files_by_session(session_id, user_key)
        out = []
        for r in rows:
            out.append(
                {
                    "id": str(r["id"]),
                    "filename": r["filename"],
                    "mime_type": r["mime_type"],
                    "size_bytes": r["size_bytes"],
                    "summary": r.get("summary"),
                    "sqlite_table_name": r.get("sqlite_table_name"),
                    "uploaded_at": r["uploaded_at"].isoformat() if r.get("uploaded_at") else None,
                }
            )
        return out

    async def build_session_schema_context_block(
        self,
        session_id: str,
        user_key: str,
        *,
        active_file_ids: list[str] | None = None,
    ) -> str:
        """Schema + sample rows for tabular uploads (SQL-first context, no vector RAG)."""
        await self._require_session(session_id, user_key)
        rows = await self._files.list_files_by_session(session_id, user_key)
        if active_file_ids:
            selected = {str(fid) for fid in active_file_ids}
            rows = [r for r in rows if str(r.get("id", "")) in selected]

        entries: list[dict[str, Any]] = []
        for r in rows:
            cached = normalize_schema_snapshot(r.get("schema_snapshot"))
            if cached:
                entries.append(cached)
                continue

            tname = r.get("sqlite_table_name")
            dbp = r.get("sqlite_db_path")
            if not tname or not dbp:
                continue
            engine_url = _sqlite_engine_url_from_stored(str(dbp))
            if not engine_url:
                continue
            dtypes: dict[str, str] = {}
            fname = str(r.get("filename") or "unknown")
            sheet = ""
            try:
                path = Path(str(r.get("local_path") or ""))
                if path.is_file():
                    parsed = parse_file(path, fname, str(r.get("mime_type") or ""))
                    if parsed.kind == "tabular" and parsed.tabular_sheets:
                        sheet = str(parsed.tabular_sheets[0].get("label") or "")
                        df = parsed.tabular_sheets[0].get("dataframe")
                        if df is not None:
                            for c in df.columns:
                                dtypes[str(c)] = str(df[c].dtype)
            except Exception:
                pass
            entry = await asyncio.to_thread(
                fetch_table_schema_entry,
                engine_url=engine_url,
                table_name=str(tname),
                filename=fname,
                sheet=sheet,
                dtypes=dtypes,
            )
            entries.append(entry)

        return format_session_schema_block(entries)

    @staticmethod
    def _looks_like_parser_summary(text: str) -> bool:
        s = (text or "").strip().lower()
        return (
            s.startswith("csv with columns:")
            or s.startswith("excel workbook ")
            or s.startswith("sqlite database ")
            or s.startswith("pdf ")
        )

    @staticmethod
    def _build_richer_summary_input(parsed: Any) -> str:
        """Build richer input for LLM summary, especially for tabular files."""
        base = str(getattr(parsed, "summary", "") or "").strip()
        if getattr(parsed, "kind", "") != "tabular":
            return base[:16000]

        lines: list[str] = [base, "", "TABULAR PROFILE:"]
        sheets = list(getattr(parsed, "tabular_sheets", []) or [])[:3]
        for i, sheet in enumerate(sheets, start=1):
            label = str(sheet.get("label") or f"Sheet{i}")
            df = sheet.get("dataframe")
            cols = [str(c) for c in (sheet.get("columns") or [])]
            lines.append(f"- Sheet: {label}")
            if cols:
                lines.append(f"  Columns ({len(cols)}): {', '.join(cols[:40])}")
            if df is None:
                continue
            try:
                lines.append(f"  Rows: {len(df)}")
                dtypes = [f"{c}:{t}" for c, t in zip(df.columns.tolist(), df.dtypes.tolist(), strict=False)]
                if dtypes:
                    lines.append(f"  Dtypes: {', '.join(dtypes[:25])}")
                null_counts = df.isna().sum()
                nz = [f"{c}={int(v)}" for c, v in null_counts.items() if int(v) > 0][:20]
                if nz:
                    lines.append(f"  Nulls: {', '.join(nz)}")
                sample = df.head(8)
                lines.append("  Sample rows:")
                lines.append(sample.to_csv(index=False))
            except Exception:
                continue
            lines.append("")
        return "\n".join(lines)[:16000]

    async def summarize_file(self, file_id: UUID, user_key: str) -> str:
        row = await self._files.get_file(file_id, user_key)
        if row is None:
            raise HTTPException(status_code=404, detail="File not found")
        existing_summary = str(row.get("summary") or "").strip()
        if existing_summary and len(existing_summary) >= 280 and not self._looks_like_parser_summary(existing_summary):
            return existing_summary
        path = Path(row["local_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File missing on disk")
        from openai import AsyncOpenAI

        parsed = parse_file(path, row["filename"], row["mime_type"])
        summary_input = self._build_richer_summary_input(parsed)
        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize this file for a chat assistant in 8-12 sentences. "
                        "Be concrete: include what the file contains, notable fields/sections, "
                        "key patterns, and potential caveats. Avoid generic wording."
                    ),
                },
                {"role": "user", "content": summary_input},
            ],
            max_tokens=650,
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        await self._files.update_file_summary(file_id, user_key, text)
        return text

    async def delete_file(self, file_id: UUID, user_key: str) -> None:
        row = await self._files.delete_file_row(file_id, user_key)
        if row is None:
            raise HTTPException(status_code=404, detail="File not found")
        sid = row.get("session_id")
        if sid:
            try:
                await self._prune_session_messages_with_file_id(str(sid), user_key, file_id)
            except Exception as e:
                logger.warning("prune session messages for deleted file failed: %s", e)
            try:
                await self._prune_session_messages_with_export_file_id(str(sid), user_key, file_id)
            except Exception as e:
                logger.warning("prune export markers for deleted file failed: %s", e)
        lp = row.get("local_path")
        if lp:
            p = Path(lp)
            p.unlink(missing_ok=True)
            if p.suffix.lower() == ".csv":
                p.with_suffix(".xlsx").unlink(missing_ok=True)
        # Drop table from sqlite if we stored db path + table name
        tname = row.get("sqlite_table_name")
        dbp = row.get("sqlite_db_path")
        if tname and dbp:
            try:
                from sqlalchemy import create_engine, text

                eng = create_engine(str(dbp))
                with eng.connect() as conn:
                    conn.execute(text(f'DROP TABLE IF EXISTS "{tname}"'))
                    conn.commit()
                eng.dispose()
            except Exception as e:
                logger.warning("drop table failed: %s", e)

    async def get_session_sqlite_url(self, session_id: str, user_key: str) -> str | None:
        """Return sqlite URL for MCP DB agent: project DB if session in project else temp session DB."""
        sess = await self._require_session(session_id, user_key)
        pid = sess.get("project_id")
        if pid and self._project_repo:
            proj = await self._project_repo.get_project_by_id(pid, user_key)
            if proj and proj.get("db_url") and not str(proj["db_url"]).startswith("placeholder"):
                return str(proj["db_url"]).strip()
        p = _temp_db_path(session_id)
        if p.is_file():
            return _sqlite_url_from_path(p)
        return None

    async def cleanup_session_files(self, session_id: str, user_key: str) -> None:
        """Remove all uploaded files and temp DB for a session (before session row delete)."""
        rows = await self._files.list_files_by_session(session_id, user_key)
        for r in rows:
            await self.delete_file(UUID(str(r["id"])), user_key)
        tpath = _temp_db_path(session_id)
        tpath.unlink(missing_ok=True)
        # Remove the session tree (import + export).
        tree = _session_file_tree_dir(user_key, session_id)
        if tree.is_dir():
            shutil.rmtree(tree, ignore_errors=True)

    def purge_session_disk(self, session_id: str, user_key: str) -> None:
        """Disk-only cleanup for a session whose row is about to be deleted in bulk
        (e.g. project deletion). Removes the temp DB file and the entire file_handle
        session tree (import + export) in one shot. Skips the per-file row/message
        pruning that ``cleanup_session_files`` does, because the session row — and
        its cascaded file rows — are being deleted anyway."""
        temp_db = _internal_data_root() / "temp_dbs" / f"{session_id}.db"
        temp_db.unlink(missing_ok=True)
        tree = _session_file_tree_dir(user_key, session_id)
        if tree.is_dir():
            shutil.rmtree(tree, ignore_errors=True)

