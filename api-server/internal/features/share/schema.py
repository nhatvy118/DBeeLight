from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ShareRecipientInput(BaseModel):
    email: str
    # one of: "view_only", "read_data", "edit_data"
    permission: str


class CreateShareRequest(BaseModel):
    session_id: str
    recipients: list[ShareRecipientInput]
    # Send a Resend email to each recipient with the accept link. Defaults
    # on for good UX; user can opt out from the share modal.
    notify_via_email: bool = True


class GenerateShareLinkRequest(BaseModel):
    session_id: Optional[str] = None
    project_id: Optional[str] = None
