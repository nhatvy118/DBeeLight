"""Render a chat session into Markdown for download.

Used by the export endpoint. PDF is delegated to the browser (the frontend
opens a print-friendly preview and the user uses "Save as PDF" from the
print dialog) — keeps the server stack free of heavy native deps like
WeasyPrint / wkhtmltopdf.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Markers the agent and frontend embed inside message content as machine
# hints (file uploads, schema previews, chart embeds, …). These are
# implementation details — strip from human-readable export.
_INTERNAL_MARKERS = [
    r"\[CREATE_TABLE_SCHEMA_JSON_START\][\s\S]*?\[CREATE_TABLE_SCHEMA_JSON_END\]",
    r"\[SCHEMA_CONFIRM_INTERNAL_START\][\s\S]*?\[SCHEMA_CONFIRM_INTERNAL_END\]",
    r"\[CHART_EMBED_URL_START\][\s\S]*?\[CHART_EMBED_URL_END\]",
    r"\[CHART_EMBED_META_START\][\s\S]*?\[CHART_EMBED_META_END\]",
    r"\[UPLOADED_EXCEL_PATH_START\][\s\S]*?\[UPLOADED_EXCEL_PATH_END\]",
    r"\[UPLOADED_EXCEL_NAME_START\][\s\S]*?\[UPLOADED_EXCEL_NAME_END\]",
    r"\[SQL_ACTION_ID_START\][\s\S]*?\[SQL_ACTION_ID_END\]",
    r"\[EXCEL_BASE64_START\][\s\S]*?\[EXCEL_BASE64_END\]",
    r"\[FILENAME_START\][\s\S]*?\[FILENAME_END\]",
    r"\[ROW_COUNT_START\][\s\S]*?\[ROW_COUNT_END\]",
    r"\[CREATE_TABLE_SCHEMA_PREVIEW\]",
    r"\[SHARED SESSION\s*[—-]\s*READ-ONLY MODE\][\s\S]*?\nUser message:\s*",
]
_MARKER_RE = re.compile("|".join(_INTERNAL_MARKERS))


def _strip_internal(text: str) -> str:
    if not text:
        return ""
    cleaned = _MARKER_RE.sub("", text)
    # Collapse runs of blank lines left behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _safe_filename(name: str) -> str:
    base = (name or "chat").strip()
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base)
    return base[:80] or "chat"


def session_to_markdown(
    *,
    session_info: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    owner_name: str | None = None,
    owner_email: str | None = None,
    project_name: str | None = None,
) -> str:
    """Produce a Markdown rendering of the chat for download."""
    title = "Chat session"
    session_id = ""
    created_at = ""
    if isinstance(session_info, dict):
        title = (session_info.get("session_name") or title).strip() or title
        session_id = str(session_info.get("session_id") or "")
        created_at = str(session_info.get("created_at") or "")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    meta_bits: list[str] = []
    if owner_name or owner_email:
        owner = " ".join(filter(None, [owner_name, f"<{owner_email}>" if owner_email else None]))
        meta_bits.append(f"**Owner**: {owner}")
    if project_name:
        meta_bits.append(f"**Project**: {project_name}")
    if created_at:
        meta_bits.append(f"**Created**: {created_at}")
    if session_id:
        meta_bits.append(f"**Session ID**: `{session_id}`")
    meta_bits.append(f"**Exported**: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("  \n".join(meta_bits))
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = _strip_internal(str(msg.get("content") or ""))
        if not content:
            continue
        heading = "User" if role == "user" else "Assistant"
        timestamp = str(msg.get("timestamp") or "").strip()
        if timestamp:
            lines.append(f"## {heading} — {timestamp}")
        else:
            lines.append(f"## {heading}")
        lines.append("")
        lines.append(content)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def filename_for_session(session_info: dict[str, Any] | None, ext: str = "md") -> str:
    name = "chat"
    if isinstance(session_info, dict):
        name = (session_info.get("session_name") or "").strip() or name
    safe = _safe_filename(name).replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe}_{timestamp}.{ext}"
