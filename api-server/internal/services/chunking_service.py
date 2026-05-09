"""Turn parsed files into chunk records (text + metadata) before embedding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from internal.services.file_parse_service import ParsedFile


@dataclass
class TextChunk:
    text: str
    metadata: dict[str, Any]


_TABULAR_ROWS_PER_CHUNK = 50
_DOC_CHARS_PER_CHUNK = 3200
_DOC_OVERLAP = 400


def _sanitize_table_base(filename: str) -> str:
    base = filename.rsplit(".", 1)[0]
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", base).strip("_")
    if not s:
        s = "uploaded_data"
    if s[0].isdigit():
        s = "t_" + s
    return s[:60].lower()


def suggested_sqlite_table_names(parsed: ParsedFile) -> list[tuple[str, str]]:
    """Return list of (sheet_label, safe_table_name)."""
    base = _sanitize_table_base(parsed.filename)
    out: list[tuple[str, str]] = []
    for i, sheet in enumerate(parsed.tabular_sheets):
        label = str(sheet.get("label") or f"sheet{i}")
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", label).strip("_") or f"sheet{i}"
        name = f"{base}_{slug}"[:63]
        if name[0].isdigit():
            name = "t_" + name
        out.append((label, name[:63]))
    return out


def chunk_parsed_file(parsed: ParsedFile, *, file_id_placeholder: str | None = None) -> list[TextChunk]:
    """Produce TextChunks for embedding. file_id filled later."""
    chunks: list[TextChunk] = []
    fid = file_id_placeholder or ""

    if parsed.kind == "tabular":
        for sheet in parsed.tabular_sheets:
            label = str(sheet.get("label") or "data")
            df = sheet["dataframe"]
            cols = sheet.get("columns") or [str(c) for c in df.columns.tolist()]
            col_line = ", ".join(cols)
            # Schema / sample chunk
            sample = df.head(5)
            sample_txt = sample.to_csv(sep="\t", index=False)
            schema_text = (
                f"File: {parsed.filename}\nSheet/table: {label}\n"
                f"Columns: {col_line}\nSample rows:\n{sample_txt}"
            )
            chunks.append(
                TextChunk(
                    text=schema_text,
                    metadata={
                        "filename": parsed.filename,
                        "sheet": label,
                        "kind": "schema",
                        "file_id": fid,
                    },
                )
            )
            # Window chunks
            header = "\t".join(str(c) for c in cols)
            n = len(df)
            start = 0
            while start < n:
                end = min(start + _TABULAR_ROWS_PER_CHUNK, n)
                sub = df.iloc[start:end]
                body = sub.to_csv(sep="\t", index=False, header=False)
                win = f"File: {parsed.filename}\nSheet: {label}\n{header}\n{body}"
                chunks.append(
                    TextChunk(
                        text=win,
                        metadata={
                            "filename": parsed.filename,
                            "sheet": label,
                            "kind": "window",
                            "row_start": int(start) + 1,
                            "row_end": int(end),
                            "file_id": fid,
                        },
                    )
                )
                start = end
        return chunks

    # document
    for part in parsed.document_parts:
        page = part.get("page", 1)
        text = str(part.get("text") or "")
        if not text.strip():
            continue
        # sliding windows
        pos = 0
        while pos < len(text):
            chunk_text = text[pos : pos + _DOC_CHARS_PER_CHUNK]
            chunks.append(
                TextChunk(
                    text=f"File: {parsed.filename}\nPage: {page}\n{chunk_text}",
                    metadata={
                        "filename": parsed.filename,
                        "page": page,
                        "kind": "text",
                        "char_start": pos,
                        "file_id": fid,
                    },
                )
            )
            pos += _DOC_CHARS_PER_CHUNK - _DOC_OVERLAP
            if pos >= len(text):
                break
    return chunks
