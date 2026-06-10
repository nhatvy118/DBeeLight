"""Files router — matches the FE contract (SessionFileMeta, {file}/{files} envelopes)."""
from __future__ import annotations
import logging

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.features.auth.deps import get_current_user_id
from app.features.files import repository as repo
from app.features.files import service
from app.features.sessions import repository as sess_repo

logger = logging.getLogger("features.files.router")

router = APIRouter(prefix="/api/files", tags=["files"])

_QUOTA_BYTES = 200 * 1024 * 1024  # 200 MB soft cap (display only)


def _meta(row: dict) -> dict:
    logger.info("→ _meta(row=%r)", row)  # autolog
    fn = row.get("filename") or ""
    created = row.get("created_at")
    return {
        "id": row["id"],
        "filename": fn,
        "mime_type": mimetypes.guess_type(fn)[0] or "application/octet-stream",
        "size_bytes": int(row.get("size_bytes") or 0),
        "summary": None,
        "sqlite_table_name": row.get("table_name"),
        "uploaded_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "sql_import_ok": bool(row.get("table_name")),
        "sql_import_warning": None,
    }


@router.post("/upload")
async def upload(session_id: str = Form(...), file: UploadFile = File(...),
                 user_id: str = Depends(get_current_user_id)):
    logger.info("→ upload(session_id=%r file=%r user_id=%r)", session_id, file, user_id)  # autolog
    if not await sess_repo.get_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found / not yours")
    content = await file.read()
    rec = await service.save_and_import(user_id, session_id, file.filename or "upload", content)
    return {"file": _meta(rec)}


@router.get("")
async def list_files(session_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ list_files(session_id=%r user_id=%r)", session_id, user_id)  # autolog
    if not await sess_repo.get_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"files": [_meta(f) for f in await repo.list_for_session(session_id)]}


@router.get("/quota")
async def quota(user_id: str = Depends(get_current_user_id)):
    logger.info("→ quota(user_id=%r)", user_id)  # autolog
    used, count = await repo.user_storage(user_id)
    return {"success": True, "used_bytes": used, "limit_bytes": _QUOTA_BYTES, "file_count": count}


@router.get("/inventory")
async def inventory(user_id: str = Depends(get_current_user_id)):
    logger.info("→ inventory(user_id=%r)", user_id)  # autolog
    return {"success": True, "files": [_meta(f) for f in await repo.list_for_user(user_id)]}


@router.get("/export-inventory")
async def export_inventory(user_id: str = Depends(get_current_user_id)):
    logger.info("→ export_inventory(user_id=%r)", user_id)  # autolog
    return {"success": True, "files": []}


@router.get("/{file_id}/download")
async def download(file_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ download(file_id=%r user_id=%r)", file_id, user_id)  # autolog
    f = await repo.get_file(file_id, user_id)
    if not f or not f.get("disk_path") or not Path(f["disk_path"]).exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(f["disk_path"], filename=f["filename"])


@router.delete("/{file_id}")
async def delete(file_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("→ delete(file_id=%r user_id=%r)", file_id, user_id)  # autolog
    await repo.delete_file(file_id, user_id)
    return {"success": True}
