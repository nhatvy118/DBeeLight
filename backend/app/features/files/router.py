"""Files router — matches the FE contract (SessionFileMeta, {file}/{files} envelopes)."""
from __future__ import annotations

import mimetypes
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.features.auth import repository as auth_repo
from app.features.auth.deps import get_current_user_id
from app.features.files import repository as repo
from app.features.files import service
from app.features.projects import service as proj_service
from app.features.sessions import repository as sess_repo

router = APIRouter(prefix="/api/files", tags=["files"])

_QUOTA_BYTES = 200 * 1024 * 1024      # 200 MB — total storage quota + per-upload cap for streamed imports
_EXCEL_MODE_MAX = 1 * 1024 * 1024     # 1 MB — mode "excel": the workbook feeds the LLM/excel-server context
_LEGACY_EXCEL_MAX = 30 * 1024 * 1024  # 30 MB — xls/xlsb/ods can't stream-parse: whole workbook lands in RAM
_CHUNK = 1024 * 1024                  # 1 MB read window

# Mirrors service's split: xlsx/xlsm stream via openpyxl read-only; the rest must fully load.
_LEGACY_EXCEL_SUFFIXES = (".xls", ".xlsb", ".ods", ".xltx", ".xltm")


def _upload_limit(filename: str, import_mode: str) -> int:
    """Per-upload cap depends on WHAT we do with the file, not just its format:
    - mode "excel": the workbook is read/edited by the LLM → tiny cap (context size);
    - mode "project_db": delimited + xlsx/xlsm imports STREAM (flat RAM) → full cap,
      legacy Excel formats must be fully loaded to parse → low cap."""
    if import_mode == "excel":
        return _EXCEL_MODE_MAX
    ext = Path(filename or "").suffix.lower()
    return _LEGACY_EXCEL_MAX if ext in _LEGACY_EXCEL_SUFFIXES else _QUOTA_BYTES


def _too_large_detail(filename: str, import_mode: str) -> str:
    if import_mode == "excel":
        return (
            "File too large to open as a workbook in chat (max 1 MB). "
            "To analyze a big dataset, import it into the database instead."
        )
    ext = Path(filename or "").suffix.lower()
    if ext in _LEGACY_EXCEL_SUFFIXES:
        return (
            "This Excel format is limited to 30 MB. For big datasets, open the file and "
            "'Save As' .xlsx or CSV, then upload that — those imports stream "
            "without a size penalty (up to 200 MB)."
        )
    return "File too large (max 200 MB)"


async def _spool_to_disk(file: UploadFile, limit: int, import_mode: str) -> Path:
    """Stream the upload to a temp file, never holding more than one chunk in RAM.
    Raises 413 (and removes the partial file) as soon as `limit` is exceeded.
    Caller is responsible for unlinking the returned path when done."""
    total = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".upload")
    try:
        while chunk := await file.read(_CHUNK):
            total += len(chunk)
            if total > limit:
                raise HTTPException(status_code=413, detail=_too_large_detail(file.filename or "", import_mode))
            tmp.write(chunk)
    except BaseException:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    tmp.close()
    return Path(tmp.name)


def _meta(row: dict) -> dict:
    fn = row.get("filename") or ""
    created = row.get("created_at")
    return {
        "id": row["id"],
        "filename": fn,
        "mime_type": mimetypes.guess_type(fn)[0] or "application/octet-stream",
        "size_bytes": int(row.get("size_bytes") or 0),
        "uploaded_at": created.isoformat() if isinstance(created, datetime) else created,
    }


_IMPORT_MODES = ("project_db", "excel")


@router.post("/upload")
async def upload(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    import_mode: str = Form(...),
    project_id: str | None = Form(None),
    target_table: str | None = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    sess = await sess_repo.get_session(session_id, user_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found / not yours")
    if import_mode not in _IMPORT_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid import_mode (expected one of {_IMPORT_MODES})")
    tmp_path = await _spool_to_disk(file, _upload_limit(file.filename or "", import_mode), import_mode)
    try:
        # Cumulative quota: per-file size was capped above; also reject when the user's TOTAL
        # stored bytes would exceed the limit. Only 'excel' persists into `files` (project_db
        # lives in the user's own DB and is not counted as our storage).
        if import_mode == "excel":
            used, _ = await repo.user_storage(user_id)
            if used + tmp_path.stat().st_size > _QUOTA_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Storage quota exceeded (200 MB total). Delete some files first.",
                )

        # project_db needs the project's resolved DSN (ownership-checked); other modes don't.
        project_db_url: str | None = None
        pid = project_id or sess.get("project_id")
        if import_mode == "project_db":
            # Viewers (non-technical) may upload + EDIT Excel files, but never import into a DB.
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
    if rec.get("tables"):  # project_db new-table import → let the FE prompt for descriptions
        resp["tables"] = rec["tables"]
    return resp


@router.get("")
async def list_files(session_id: str, user_id: str = Depends(get_current_user_id)):
    if not await sess_repo.get_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"files": [_meta(f) for f in await repo.list_for_session(session_id)]}


@router.get("/quota")
async def quota(user_id: str = Depends(get_current_user_id)):
    used, count = await repo.user_storage(user_id)
    return {"success": True, "used_bytes": used, "limit_bytes": _QUOTA_BYTES, "file_count": count}


@router.get("/inventory")
async def inventory(user_id: str = Depends(get_current_user_id)):
    return {"success": True, "files": [_meta(f) for f in await repo.list_for_user(user_id)]}


@router.get("/export-inventory")
async def export_inventory(user_id: str = Depends(get_current_user_id)):
    return {"success": True, "files": []}


@router.get("/{file_id}/download")
async def download(file_id: str, user_id: str = Depends(get_current_user_id)):
    f = await repo.get_file(file_id, user_id)
    if not f or not f.get("disk_path") or not Path(f["disk_path"]).exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(f["disk_path"], filename=f["filename"])


@router.delete("/{file_id}")
async def delete(file_id: str, user_id: str = Depends(get_current_user_id)):
    await service.delete_file(user_id, file_id)  # also drops the session table / unlinks the disk file
    return {"success": True}
