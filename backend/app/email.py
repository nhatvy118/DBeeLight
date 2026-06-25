"""Transactional email via Resend (HTTP API).

Every send is BEST-EFFORT: if Resend isn't configured (no API key) or the call fails, we log and
return False — the caller's action (invite / share) must still succeed. Nothing here ever raises.
"""
from __future__ import annotations

import html
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("email")

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = 10.0


async def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Send one email. Returns True on a 2xx from Resend, False if disabled or on any failure."""
    s = get_settings()
    if not s.resend_api_key:
        logger.info("email disabled (no RESEND_API_KEY) — skipped %r to %s", subject, to)
        return False
    if not to or "@" not in to:
        return False
    payload = {
        "from": s.resend_from,
        "to": [to],
        "subject": subject,
        "html": html_body,
        **({"text": text_body} if text_body else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {s.resend_api_key}"},
                json=payload,
            )
        if resp.status_code // 100 == 2:
            return True
        logger.warning("resend send failed (%s) to %s: %s", resp.status_code, to, resp.text[:300])
        return False
    except Exception as e:  # noqa: BLE001 — email must never break the calling flow
        logger.warning("resend send error to %s: %s", to, e)
        return False


def _app_url() -> str:
    s = get_settings()
    return (s.frontend_url or "").rstrip("/") or "https://app.dbeelight.local"


def _button(href: str, label: str) -> str:
    return (
        f'<a href="{html.escape(href)}" '
        'style="display:inline-block;padding:11px 20px;background:#E0A82E;color:#1a1a1a;'
        'font-weight:600;text-decoration:none;border-radius:8px">'
        f"{html.escape(label)}</a>"
    )


def _wrap(title: str, body_html: str) -> str:
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:520px;margin:0 auto;color:#1a1a1a;line-height:1.5">'
        f'<h2 style="font-size:20px;margin:0 0 14px">{html.escape(title)}</h2>'
        f"{body_html}"
        '<p style="font-size:12px;color:#888;margin-top:28px">'
        "You received this because someone added you on LightDBee. If this wasn’t expected, you can "
        "ignore this email.</p></div>"
    )


async def send_invite_email(to: str, role: str) -> bool:
    """Notify a newly invited person that they can sign in to LightDBee."""
    app = _app_url()
    role_h = html.escape(role)
    body = _wrap(
        "You’ve been invited to LightDBee",
        f'<p>An admin invited you to LightDBee as a <strong>{role_h}</strong>. '
        f"Sign in with this email address to get started.</p>"
        f'<p style="margin:22px 0">{_button(app, "Open LightDBee")}</p>',
    )
    text = f"You've been invited to LightDBee as a {role}. Sign in at {app}"
    return await send_email(to, "You’ve been invited to LightDBee", body, text)


async def send_share_email(to: str, owner_name: str, project_name: str, permission: str) -> bool:
    """Notify a person that a project's data was shared with them."""
    app = _app_url()
    owner_h = html.escape(owner_name or "Someone")
    proj_h = html.escape(project_name or "a project")
    access = "view and query" if permission == "edit" else "view"
    body = _wrap(
        f"{owner_h} shared a project with you",
        f"<p><strong>{owner_h}</strong> shared the project "
        f"<strong>{proj_h}</strong> with you on LightDBee. "
        f"You can {access} its data.</p>"
        f'<p style="margin:22px 0">{_button(app, "Open in LightDBee")}</p>',
    )
    text = f"{owner_name or 'Someone'} shared the project '{project_name}' with you. Open {app}"
    return await send_email(to, f"{owner_name or 'Someone'} shared “{project_name}” with you", body, text)
