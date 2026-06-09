from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Permission = Literal["view_only", "read_data", "edit_data"]


class ShareRecipientInput(BaseModel):
    email: str
    permission: Permission


class CreateShareRequest(BaseModel):
    recipients: list[ShareRecipientInput]
    notify_via_email: bool = True
