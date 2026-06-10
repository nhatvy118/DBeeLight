"""Send share-invite emails via Resend (optional). Not configured → treated as disabled."""
from __future__ import annotations

import logging
import os

import httpx

from app.config import get_settings

logger = logging.getLogger("share.email")


def is_configured() -> bool:
    logger.info("→ is_configured()")  # autolog
    return bool(os.getenv("RESEND_API_KEY", "").strip())


async def send_share_notification(*, to_email: str, owner_name: str, session_name: str | None,
                                  permission: str, accept_token: str) -> None:
    logger.info("→ send_share_notification(to_email=%r owner_name=%r session_name=%r permission=%r accept_token=***)", to_email, owner_name, session_name, permission)  # autolog
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Email not configured (RESEND_API_KEY)")
    from_addr = os.getenv("RESEND_FROM", "DBeeLight <noreply@dbeelight.local>")
    fe = get_settings().frontend_url.rstrip("/")
    accept_url = f"{fe}/share/accept/{accept_token}"
    html = (
        f"<p>{owner_name} shared a chat with you"
        f"{(' “' + session_name + '”') if session_name else ''} "
        f"(permission: {permission}).</p>"
        f'<p><a href="{accept_url}">Open the shared chat</a></p>'
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_addr, "to": [to_email],
                  "subject": "A chat has been shared with you", "html": html},
        )
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend error {resp.status_code}: {resp.text[:200]}")
