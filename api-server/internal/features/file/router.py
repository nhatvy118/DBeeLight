from __future__ import annotations

import csv
import logging
import re
import uuid
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from internal.dependencies import get_user_key
from internal.features.file.dependencies import get_file_service
from internal.features.file.schema import UploadExcelOk
from internal.features.file.service import (
    USER_STORAGE_LIMIT_BYTES,
    FileService,
    excel_mcp_staging_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])


# ----------------------------- Session files -----------------------------


@router.post("/api/files/upload")
async def upload_session_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    project_id: str | None = Form(None),
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


# ------------------------------- Excel upload -----------------------------

_ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}
# Extensions our MCP Excel server (openpyxl-based) can read directly.
_NATIVE_XLSX_EXTENSIONS = {"xlsx", "xlsm", "xltx", "xltm"}


def _safe_filename(name: str) -> str:
    base = (name or "").strip().split("/")[-1].split("\\")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip()
    return base or "upload.xlsx"


def _csv_to_xlsx(csv_path: Path, xlsx_path: Path) -> None:
    """Convert a CSV file to .xlsx in place (sheet name "Sheet1").

    The MCP Excel server is openpyxl-only and cannot read CSV. We do the
    conversion at upload time so the agent always works with .xlsx.
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        sample = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect=dialect)
        for row in reader:
            ws.append(row)

    wb.save(xlsx_path)


@router.post("/api/excel/upload", response_model=UploadExcelOk)
async def upload_excel(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    user_key: str = Depends(get_user_key),
) -> UploadExcelOk:
    """Upload an Excel/CSV file so the MCP Excel tools can read it by path."""
    original_name = _safe_filename(file.filename or "")
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .xlsx, .xls, .csv files are supported")

    try:
        staging_dir = excel_mcp_staging_dir(user_key or "anonymous", session_id)
        staging_dir.mkdir(parents=True, exist_ok=True)

        stored_basename = uuid.uuid4().hex
        raw_dest = staging_dir / f"{stored_basename}_{original_name}"
        size_bytes = 0
        with raw_dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                f.write(chunk)

        if ext in _NATIVE_XLSX_EXTENSIONS:
            agent_path = raw_dest
            stored_name = raw_dest.name
        elif ext == "csv":
            xlsx_name = f"{stored_basename}_{Path(original_name).stem}.xlsx"
            agent_path = staging_dir / xlsx_name
            try:
                _csv_to_xlsx(raw_dest, agent_path)
            except Exception as e:
                logger.exception("Failed to convert CSV to XLSX")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to convert CSV to XLSX: {e}",
                ) from e
            stored_name = xlsx_name
        else:
            raise HTTPException(
                status_code=400,
                detail="Legacy .xls files are not supported. Please upload .xlsx or .csv.",
            )

        return UploadExcelOk(
            file={
                "original_name": original_name,
                "stored_name": stored_name,
                "server_path": str(agent_path),
                "size_bytes": size_bytes,
                "session_id": session_id,
                "project_id": project_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}") from e
