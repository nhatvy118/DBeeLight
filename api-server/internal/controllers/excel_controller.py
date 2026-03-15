from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from internal.controllers.schemas import UploadExcelOk
from internal.dependencies import get_user_key


router = APIRouter()


_ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}


def _safe_filename(name: str) -> str:
    # Keep it simple: remove path separators and weird chars.
    base = (name or "").strip().split("/")[-1].split("\\")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip()
    return base or "upload.xlsx"


@router.post("/api/excel/upload", response_model=UploadExcelOk)
async def upload_excel(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    user_key: str = Depends(get_user_key),
) -> UploadExcelOk:
    """
    Upload an Excel/CSV file so the MCP Excel tools can read it by path.

    Returns the saved file path (server-side) so the frontend can pass it back
    into chat messages when asking the agent to import/analyze.
    """
    original_name = _safe_filename(file.filename or "")
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .xlsx, .xls, .csv files are supported")

    try:
        # api-server/ as the root for uploads
        api_server_root = Path(__file__).resolve().parents[2]
        uploads_dir = api_server_root / "uploads" / (user_key or "anonymous")
        uploads_dir.mkdir(parents=True, exist_ok=True)

        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        dest = uploads_dir / stored_name

        # Stream-save to disk
        size_bytes = 0
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                f.write(chunk)

        return UploadExcelOk(
            file={
                "original_name": original_name,
                "stored_name": stored_name,
                "server_path": str(dest),
                "size_bytes": size_bytes,
                "session_id": session_id,
                "project_id": project_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}") from e

