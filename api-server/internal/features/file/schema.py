from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class UploadExcelOk(BaseModel):
    success: bool = True
    file: dict[str, Any]
