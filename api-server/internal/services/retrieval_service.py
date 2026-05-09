"""Format retrieved chunks for LLM injection with token budget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ~4000 tokens safety cap (approx 4 chars per token)
_MAX_CONTEXT_CHARS = 16000


@dataclass
class ChunkResult:
    chunk_text: str
    metadata: dict[str, Any]
    distance: float


def format_chunks_as_context_block(
    chunks: list[ChunkResult],
    available_tables: list[dict[str, Any]] | None = None,
) -> str:
    """Build ``[ATTACHED FILES CONTEXT]`` block with optional SQLite table mapping.

    ``available_tables`` entries should include: filename, sheet (optional),
    sqlite_table_name, columns (list[str]).
    """
    available_tables = available_tables or []
    if not chunks and not available_tables:
        return ""

    lines: list[str] = ["[ATTACHED FILES CONTEXT]"]
    used = len(lines[0]) + 1

    def _would_exceed(extra: str) -> bool:
        return used + len(extra) + 1 > _MAX_CONTEXT_CHARS

    if available_tables:
        hdr = "AVAILABLE SQLITE TABLES (use these EXACT names in SQL):"
        if _would_exceed(hdr):
            lines.append("... [context truncated for length]")
            return "\n".join(lines)
        lines.append(hdr)
        used += len(hdr) + 1

        for entry in available_tables:
            fname = str(entry.get("filename") or "unknown")
            sheet = str(entry.get("sheet") or "").strip()
            tname = str(entry.get("sqlite_table_name") or "").strip()
            cols = entry.get("columns") or []
            col_list = [str(c) for c in cols] if isinstance(cols, list) else []
            col_str = ", ".join(col_list) if col_list else "(could not list columns)"

            line1 = f"- file: {fname}"
            if sheet:
                line1 += f" | sheet: {sheet}"
            block_lines = [
                line1,
                f"  table: `{tname}`",
                f"  columns: {col_str}",
            ]
            for bl in block_lines:
                if _would_exceed(bl):
                    lines.append("... [context truncated for length]")
                    return "\n".join(lines)
                lines.append(bl)
                used += len(bl) + 1

        sep = "---"
        if _would_exceed(sep):
            lines.append("... [context truncated for length]")
            return "\n".join(lines)
        lines.append(sep)
        used += len(sep) + 1

    if chunks:
        intro = (
            "The following excerpts were retrieved from files uploaded in this chat session."
        )
        if _would_exceed(intro):
            lines.append("... [context truncated for length]")
            return "\n".join(lines)
        lines.append(intro)
        used += len(intro) + 1

        sep2 = "---"
        if _would_exceed(sep2):
            lines.append("... [context truncated for length]")
            return "\n".join(lines)
        lines.append(sep2)
        used += len(sep2) + 1

        for c in chunks:
            meta = c.metadata if isinstance(c.metadata, dict) else {}
            fname = meta.get("filename", "unknown")
            kind = meta.get("kind", "")
            sheet = meta.get("sheet", "")
            head = f"<file:{fname}"
            if sheet:
                head += f" | {sheet}"
            if kind:
                head += f" | {kind}"
            head += ">"
            block = f"{head}\n{c.chunk_text}\n"
            if used + len(block) > _MAX_CONTEXT_CHARS:
                lines.append("... [context truncated for length]")
                break
            lines.append(block)
            lines.append("---")
            used += len(block) + 5
    elif available_tables:
        note = (
            "No indexed excerpts matched this query; use SQL on the tables listed above."
        )
        if not _would_exceed(note):
            lines.append(note)
            used += len(note) + 1

    return "\n".join(lines)
