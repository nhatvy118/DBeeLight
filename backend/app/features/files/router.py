"""Files router — matches the FE contract (SessionFileMeta, {file}/{files} envelopes)."""
from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.features.auth.deps import get_current_user_id
from app.features.files import repository as repo
from app.features.files import service
from app.features.projects import service as proj_service
from app.features.sessions import repository as sess_repo

router = APIRouter(prefix="/api/files", tags=["files"])

_QUOTA_BYTES = 200 * 1024 * 1024  # 200 MB — enforced per-upload + shown as quota
_CHUNK = 1024 * 1024  # 1 MB read window


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Read in chunks, aborting as soon as the limit is exceeded so an oversized
    upload never gets fully loaded into RAM."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="File too large (max 200 MB)")
        chunks.append(chunk)
    return b"".join(chunks)


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


_IMPORT_MODES = ("project_db", "qa", "excel")


@router.post("/upload")
async def upload(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    import_mode: str = Form(...),
    project_id: str | None = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    sess = await sess_repo.get_session(session_id, user_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found / not yours")
    if import_mode not in _IMPORT_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid import_mode (expected one of {_IMPORT_MODES})")
    content = await _read_limited(file, _QUOTA_BYTES)

    # project_db needs the project's resolved DSN (ownership-checked); other modes don't.
    project_db_url: str | None = None
    pid = project_id or sess.get("project_id")
    if import_mode == "project_db":
        if not pid:
            raise HTTPException(status_code=400, detail="No project to import into")
        project_db_url = await proj_service.resolve_db_url(pid, user_id)
        if not project_db_url:
            raise HTTPException(status_code=400, detail="Project has no database connected")

    try:
        rec = await service.save_and_import(
            user_id, session_id, file.filename or "upload", content,
            mode=import_mode, project_id=pid, project_db_url=project_db_url,
        )
    except service.FileImportError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"file": _meta(rec)}


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
    await repo.delete_file(file_id, user_id)
    return {"success": True}
