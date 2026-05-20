from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from internal.dependencies import get_user_key
from internal.features.file.dependencies import get_file_service
from internal.features.file.service import (
    USER_STORAGE_LIMIT_BYTES,
    FileService,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])


# ----------------------------- Session files -----------------------------


@router.post("/api/files/upload")
async def upload_session_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    project_id: str | None = Form(None),
    use_project_db: bool | None = Form(None),
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required to upload files")
    meta = await service.upload_file(
        session_id=session_id.strip(),
        user_key=user_key,
        upload=file,
        project_id_override=(project_id.strip() if project_id else None),
        use_project_db=use_project_db,
    )
    return {"success": True, "file": meta}


@router.get("/api/files/quota")
async def get_files_quota(
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    import_used, export_used, used = await service.get_storage_quota_breakdown(user_key)
    limit = USER_STORAGE_LIMIT_BYTES
    return {
        "success": True,
        "used_bytes": used,
        "import_used_bytes": import_used,
        "export_used_bytes": export_used,
        "limit_bytes": limit,
        "remaining_bytes": max(0, limit - used),
    }


@router.get("/api/files/inventory")
async def list_user_files_inventory(
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    files = await service.list_user_files_inventory(user_key)
    return {"success": True, "files": files}


@router.get("/api/files/export-inventory")
async def list_export_files_inventory(
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    files = await service.list_chat_export_files_inventory(user_key)
    return {"success": True, "files": files}


@router.get("/api/files")
async def list_session_files(
    session_id: str,
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    files = await service.get_session_files(session_id.strip(), user_key)
    return {"success": True, "files": files}


@router.get("/api/files/{file_id}/download")
async def download_stored_session_file(
    file_id: str,
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    """Download a session file from ``file_handle/{user}/{session}/import|export/``."""
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    try:
        fid = UUID(file_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid file id") from e
    row = await service.get_file_for_download(fid, user_key)
    path = row["path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")
    media = row.get("mime_type") or "application/octet-stream"
    return FileResponse(
        str(path),
        filename=row["filename"],
        media_type=str(media),
    )


@router.delete("/api/files/{file_id}")
async def delete_session_file(
    file_id: str,
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    try:
        fid = UUID(file_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid file id") from e
    await service.delete_file(fid, user_key)
    return {"success": True}


@router.post("/api/files/{file_id}/summarize")
async def summarize_session_file(
    file_id: str,
    user_key: str = Depends(get_user_key),
    service: FileService = Depends(get_file_service),
):
    if user_key == "anonymous":
        raise HTTPException(status_code=401, detail="Login required")
    try:
        fid = UUID(file_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid file id") from e
    summary = await service.summarize_file(fid, user_key)
    return {"success": True, "summary": summary}


