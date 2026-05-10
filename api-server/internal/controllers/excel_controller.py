from __future__ import annotations

import csv
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from internal.controllers.schemas import UploadExcelOk
from internal.dependencies import get_user_key
from internal.usecases.file_usecase import excel_mcp_staging_dir

logger = logging.getLogger(__name__)
router = APIRouter()


_ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}
# Extensions our MCP Excel server (openpyxl-based) can read directly.
_NATIVE_XLSX_EXTENSIONS = {"xlsx", "xlsm", "xltx", "xltm"}


def _safe_filename(name: str) -> str:
    # Keep it simple: remove path separators and weird chars.
    base = (name or "").strip().split("/")[-1].split("\\")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip()
    return base or "upload.xlsx"


def _csv_to_xlsx(csv_path: Path, xlsx_path: Path) -> None:
    """Convert a CSV file to .xlsx in place (sheet name "Sheet1").

    The MCP Excel server is openpyxl-only and cannot read CSV. We do the
    conversion at upload time so the agent always works with .xlsx.
    """
    from openpyxl import Workbook  # local import — keeps cold start fast

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Detect delimiter from first non-empty line; default to comma.
    sample: str
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
    """
    Upload an Excel/CSV file so the MCP Excel tools can read it by path.

    Files are stored under ``file_handle/{user}/excel_mcp/`` or
    ``file_handle/{user}/{session}/excel_mcp/``. This staging area is not
    counted toward the 5 GB indexed-session storage cap.

    CSV uploads are converted to .xlsx server-side because the agent's
    Excel MCP server (openpyxl-based) only reads .xlsx-family formats.
    The original filename is still reported back so the chat UI can show
    the file the user actually selected.
    """
    original_name = _safe_filename(file.filename or "")
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .xlsx, .xls, .csv files are supported")

    try:
        staging_dir = excel_mcp_staging_dir(user_key or "anonymous", session_id)
        staging_dir.mkdir(parents=True, exist_ok=True)

        stored_basename = uuid.uuid4().hex
        # Preserve the user's filename for raw-disk debugging / cleanup, but
        # the path the agent receives always ends in .xlsx.
        raw_dest = staging_dir / f"{stored_basename}_{original_name}"
        size_bytes = 0
        with raw_dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                f.write(chunk)

        # Decide what path to hand back to the agent.
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
            # .xls — openpyxl can't read these either. Reject for now;
            # a future improvement could convert via pyexcel or libreoffice.
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
