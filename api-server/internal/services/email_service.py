"""Transactional email via Resend (resend.com).

Stdlib ``urllib`` to keep deps light — Resend's REST API is a single
``POST /emails`` endpoint with a JSON body, no SDK needed.

Configuration (from env, read once at boot via ``EmailService.from_env``):
- ``RESEND_API_KEY``: required for sending. If absent, ``from_env`` returns
  ``None`` and the share flow silently skips email (logged as info).
- ``EMAIL_FROM_ADDRESS``: ``"Display Name <addr@domain>"`` or just
  ``"addr@domain"``. Defaults to Resend's sandbox sender for dev.
- ``APP_URL``: frontend origin used to render absolute accept URLs in
  emails (e.g. ``http://localhost:5173``).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"
_DEFAULT_FROM = "onboarding@resend.dev"


PERMISSION_BLURB = {
    "view_only": "View only — you can read the chat history but cannot send messages.",
    "read_data": "Read data — you can continue chatting and run SELECT queries, but not modify data or schema.",
    "edit_data": "Full access — you can continue chatting with full read/write capabilities.",
}


class EmailService:
    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        app_url: str,
    ) -> None:
        self._api_key = api_key
        self._from = from_address
        self._app_url = app_url.rstrip("/")

    @classmethod
    def from_env(cls) -> Optional["EmailService"]:
        api_key = (os.getenv("RESEND_API_KEY") or "").strip()
        if not api_key:
            logger.info(
                "EmailService disabled: RESEND_API_KEY not set. Share flow "
                "will skip email notifications."
            )
            return None
        return cls(
            api_key=api_key,
            from_address=(os.getenv("EMAIL_FROM_ADDRESS") or "").strip() or _DEFAULT_FROM,
            app_url=(os.getenv("APP_URL") or "http://localhost:5173").strip(),
        )

    async def send_share_notification(
        self,
        *,
        to_email: str,
        owner_name: str,
        owner_email: Optional[str],
        session_name: Optional[str],
        permission: str,
        accept_token: str,
    ) -> None:
        """Send a share-invitation email. Raises on Resend API errors."""
        accept_url = f"{self._app_url}/share/accept/{accept_token}"
        title = (session_name or "a chat").strip() or "a chat"
        permission_text = PERMISSION_BLURB.get(permission, permission)

        subject = f"{owner_name} shared {title} with you on Chat-App"
        text_body = self._render_text(
            owner_name=owner_name,
            owner_email=owner_email,
            session_name=title,
            permission_text=permission_text,
            to_email=to_email,
            accept_url=accept_url,
        )
        html_body = self._render_html(
            owner_name=owner_name,
            owner_email=owner_email,
            session_name=title,
            permission_text=permission_text,
            to_email=to_email,
            accept_url=accept_url,
        )

        payload = {
            "from": self._from,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        }
        # Resend's request is sync HTTP; run in a thread so we don't block
        # the event loop.
        await asyncio.to_thread(self._post, payload)

    def _post(self, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _RESEND_ENDPOINT,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # Cloudflare in front of Resend rejects requests with no UA
                # (returns 1010). Identify ourselves explicitly.
                "User-Agent": "ChatApp-EmailService/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
                logger.info(f"EmailService: Resend OK ({resp.status}): {body[:200]}")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                pass
            raise RuntimeError(
                f"Resend HTTP {e.code}: {err_body or e.reason}"
            ) from e

    @staticmethod
    def _render_text(*, owner_name, owner_email, session_name, permission_text, to_email, accept_url) -> str:
        owner_line = owner_name + (f" ({owner_email})" if owner_email else "")
        return (
            f"{owner_line} shared the chat session \"{session_name}\" with you on Chat-App.\n\n"
            f"Access level\n"
            f"------------\n"
            f"{permission_text}\n\n"
            f"Open the chat:\n"
            f"{accept_url}\n\n"
            f"Note: you must sign in with {to_email} to access this share.\n"
        )

    @staticmethod
    def _render_html(*, owner_name, owner_email, session_name, permission_text, to_email, accept_url) -> str:
        owner_safe = html.escape(owner_name)
        owner_email_safe = html.escape(owner_email or "")
        session_safe = html.escape(session_name)
        permission_safe = html.escape(permission_text)
        to_email_safe = html.escape(to_email)
        accept_url_safe = html.escape(accept_url, quote=True)
        owner_block = (
            f"<strong>{owner_safe}</strong>"
            + (f" &lt;{owner_email_safe}&gt;" if owner_email else "")
        )
        return f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 24px auto; padding: 24px; color: #111;">
  <h2 style="margin: 0 0 16px; font-size: 18px;">A chat was shared with you</h2>
  <p style="margin: 0 0 12px; color: #444;">
    {owner_block} shared the chat session
    <strong>“{session_safe}”</strong> with you on Chat-App.
  </p>
  <div style="background: #f4f5f7; border-radius: 8px; padding: 12px 14px; margin: 16px 0; color: #333; font-size: 14px;">
    <strong style="display: block; margin-bottom: 4px;">Access level</strong>
    {permission_safe}
  </div>
  <p style="margin: 24px 0;">
    <a href="{accept_url_safe}"
       style="display: inline-block; padding: 10px 18px; background: #4f46e5; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600;">
      Open shared chat
    </a>
  </p>
  <p style="font-size: 12px; color: #888; margin-top: 24px;">
    You must sign in with <strong>{to_email_safe}</strong> to access this share.
    If you didn't expect this, you can safely ignore the email.
  </p>
</body>
</html>"""
