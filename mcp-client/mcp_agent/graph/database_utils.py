"""Database utilities - SQL parsing, preview formatting, etc.

Shared utilities for all database workflows (readonly, create_table, mutation).
"""

import json
import logging
import re
from typing import Any, Optional, List

logger = logging.getLogger(__name__)

_DELETE_PREVIEW_ROW_CAP = 200
_INSERT_PREVIEW_MAX_ROWS = 80
_INSERT_PREVIEW_CELL_MAX = 500


def detect_db_type(agent) -> str:
    """Detect whether the connected database is SQLite or PostgreSQL.

    **Project rule (thesis):**
    - If the current chat session belongs to a project_id → SQLite (project DB file)
    - Otherwise → PostgreSQL

    ChatUseCase sets ``agent.connection_info = {"engine": "sqlite" | "postgresql"}``.
    """
    if not agent:
        return "postgresql"

    info = getattr(agent, "connection_info", None)
    if isinstance(info, dict):
        engine = str(info.get("engine") or "").lower().strip()
        if engine in {"sqlite", "postgresql", "postgres"}:
            return "postgresql" if engine == "postgres" else engine

    # Safe default for non-project chats: PostgreSQL.
    return "postgresql"

    
def parse_table_names_from_list_tools(text: str) -> list[str]:
    """Parse MCP ``list_tables`` text like ``Tables in database: a, b``."""
    s = (text or "").strip()
    if not s:
        return []
    m = re.search(r"tables?\s+in\s+database:\s*(.+?)(?:\n|$)", s, re.I | re.DOTALL)
    if not m:
        return []
    rest = m.group(1).strip()
    return [t.strip() for t in re.split(r"[\s,]+", rest) if t.strip()]


def build_mutation_schema_context_block(
    table_schema: dict[str, Any],
    *,
    operation: str = "",
) -> str:
    """Format schema context for mutation SQL generation (operation-aware)."""
    if not table_schema:
        return ""

    schema_mode = str(table_schema.get("schema_mode") or "existing_table").strip()
    op = str(operation or "").strip().upper()
    if op == "CREATE":
        schema_mode = "new_table"
    elif op == "ALTER":
        schema_mode = "alter_table"

    target_tables = [
        str(t).strip()
        for t in (table_schema.get("tables") or [])
        if str(t).strip()
    ]
    descriptions = table_schema.get("descriptions") or {}
    if not isinstance(descriptions, dict):
        descriptions = {}

    if schema_mode == "new_table":
        if not target_tables:
            return (
                "NEW TABLE — no existing table schema. "
                "Define the full CREATE TABLE statement from the user request."
            )
        names = ", ".join(f"`{t}`" for t in target_tables)
        return (
            f"NEW TABLE — `{names}` does not exist yet.\n"
            "Define all columns and types from the user request. "
            "Do not copy column names from other tables unless the user asked."
        )

    if not target_tables:
        return ""

    lines: list[str] = []
    if schema_mode == "alter_table":
        lines.extend(
            [
                "ALTER TABLE — below are EXISTING columns on the target table(s).",
                "The user may ADD or RENAME columns; those new names are NOT listed below.",
                "Use existing names when referencing current columns; use the user request for new names/types.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "TARGET TABLE SCHEMA — use ONLY the table name(s) and columns listed below.",
                "Do NOT invent column names.",
                "",
            ]
        )

    for t in target_tables:
        desc = descriptions.get(t)
        if not isinstance(desc, str) or not desc.strip():
            continue
        lines.append(f"Table `{t}` existing columns:")
        lines.append(desc.strip())
        lines.append("")

    if len(lines) <= 3:
        return ""
    return "\n".join(lines).strip()


def get_sql_system_prompt(db_type: str, *, operation: str = "") -> str:
    """Return SQL generation system prompt for the given database type."""
    op = str(operation or "").strip().upper()
    if op == "CREATE":
        schema_rule = (
            "You are creating a new table. Column names and types come from the user request "
            "(and NEW TABLE notes if present), not from existing tables. "
            "Return ONLY the SQL, no markdown."
        )
    elif op == "ALTER":
        schema_rule = (
            "An ALTER TABLE SCHEMA section lists existing columns only. "
            "New or renamed columns are defined in the user request. "
            "Return ONLY the SQL, no markdown."
        )
    else:
        schema_rule = (
            "A TARGET TABLE SCHEMA section lists existing columns on the target table. "
            "Use ONLY those exact table and column names. "
            "For INSERT, include every NOT NULL column that has no DEFAULT unless it is auto-generated. "
            "Return ONLY the SQL, no markdown."
        )
    if db_type == "postgresql":
        return (
            "You are a PostgreSQL expert. Generate SQL query using PostgreSQL syntax. "
            "Use SERIAL or BIGSERIAL for auto-increment primary keys, not AUTOINCREMENT. "
            + schema_rule
        )
    # Default to SQLite
    return (
        "You are a SQLite expert. Generate SQL query using SQLite syntax. "
        "Use INTEGER PRIMARY KEY AUTOINCREMENT for auto-increment primary keys. "
        + schema_rule
    )


def get_select_system_prompt(db_type: str) -> str:
    """Return SELECT generation system prompt for the given database type."""
    attached_rule = (
        "If the additional context includes a section "
        "'AVAILABLE SQLITE TABLES (use these EXACT names in SQL)', you MUST use the "
        "exact `table` backtick name shown there and only columns listed under "
        "`columns:` for that table. Do NOT invent table or column names."
    )
    if db_type == "postgresql":
        return (
            "You are a PostgreSQL expert. Generate exactly one read-only SELECT statement "
            "using PostgreSQL syntax for the user's request. Return ONLY SQL, no markdown. "
            + attached_rule
        )
    # Default to SQLite
    return (
        "You are a SQLite expert. Generate exactly one read-only SELECT statement "
        "using SQLite syntax for the user's request. Return ONLY SQL, no markdown. "
        + attached_rule
    )


def extract_attached_files_context_block(user_message: str) -> str:
    """Return the ``[ATTACHED FILES CONTEXT]`` block if present (for SQL generation).

    Chat augments turns as ``<block>\\n\\nUSER MESSAGE:\\n<query>``; we keep the
    full block so SELECT generation sees AVAILABLE SQLITE TABLES + excerpts.
    """
    msg = (user_message or "").strip()
    if "[ATTACHED FILES CONTEXT]" not in msg:
        return ""
    sep = "\n\nUSER MESSAGE:\n"
    if sep in msg:
        head = msg.split(sep, 1)[0].strip()
        if head.startswith("[ATTACHED FILES CONTEXT]"):
            return head
    idx = msg.find("[ATTACHED FILES CONTEXT]")
    return msg[idx:].strip()


def get_create_table_system_prompt(db_type: str) -> str:
    """Return CREATE TABLE system prompt for the given database type."""
    if db_type == "postgresql":
        return (
            "You are a PostgreSQL expert. Generate CREATE TABLE SQL using PostgreSQL syntax. "
            "Use SERIAL or BIGSERIAL for auto-increment primary keys. "
            "Return ONLY the SQL."
        )
    # Default to SQLite
    return (
        "You are a SQLite expert. Generate CREATE TABLE SQL using SQLite syntax. "
        "Use INTEGER PRIMARY KEY AUTOINCREMENT for auto-increment primary keys. "
        "Return ONLY the SQL."
    )


# === SQL parsing utilities ===

def strip_sql_fences(text: str) -> str:
    """Strip SQL code fences from text."""
    t = (text or "").strip()
    m = re.match(r"^```(?:sql)?\s*([\s\S]*?)\s*```\s*$", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    inner = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", t, re.IGNORECASE)
    if inner:
        return inner.group(1).strip()
    return t


def delete_sql_to_select_preview(delete_sql: str) -> Optional[str]:
    """Map DELETE ... to a bounded SELECT * for row preview (read-only)."""
    s = strip_sql_fences((delete_sql or "").strip().rstrip(";"))
    m = re.match(
        r"^\s*DELETE\s+FROM\s+([`\"\w.]+)\s*(.*)\s*$",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    table_ref = m.group(1).strip()
    tail = (m.group(2) or "").strip()
    if not tail:
        sel = f"SELECT * FROM {table_ref}"
    elif tail.upper().startswith("WHERE"):
        if ";" in tail:
            return None
        sel = f"SELECT * FROM {table_ref} {tail}"
    else:
        return None
    if "LIMIT" not in sel.upper():
        sel = f"{sel.rstrip(';')} LIMIT {_DELETE_PREVIEW_ROW_CAP}"
    return sel


def update_sql_to_select_preview(update_sql: str) -> Optional[str]:
    """Map UPDATE ... SET ... [WHERE ...] to a bounded SELECT * for row preview.

    Handles multiple UPDATE statements by combining all WHERE conditions with OR
    so the preview shows every row that would be affected.
    """
    s = strip_sql_fences((update_sql or "").strip().rstrip(";"))
    # Extract table name from the first UPDATE statement.
    m = re.match(r"^\s*UPDATE\s+([`\"\w.]+)\s+SET\b", s, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    table_ref = m.group(1).strip()

    # Collect every WHERE clause across all UPDATE statements.
    # Pattern: WHERE <condition> followed by ; or end-of-string or next UPDATE.
    where_conditions = re.findall(
        r"\bWHERE\b\s+(.*?)(?=\s*;|\s*$)",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    conditions = [c.strip() for c in where_conditions if c.strip()]

    if conditions:
        if len(conditions) == 1:
            where_clause = conditions[0]
        else:
            where_clause = " OR ".join(f"({c})" for c in conditions)
        sel = f"SELECT * FROM {table_ref} WHERE {where_clause}"
    else:
        sel = f"SELECT * FROM {table_ref}"

    if "LIMIT" not in sel.upper():
        sel = f"{sel.rstrip(';')} LIMIT {_DELETE_PREVIEW_ROW_CAP}"
    return sel


def drop_sql_to_select_preview(drop_sql: str) -> Optional[str]:
    """Map DROP TABLE|VIEW ... to SELECT * (rows that would be removed / lost)."""
    s = strip_sql_fences((drop_sql or "").strip().rstrip(";"))
    if ";" in s:
        return None
    m = re.match(
        r"^\s*DROP\s+(?:TABLE|VIEW)\s+(?:IF\s+EXISTS\s+)?([`\"\w.]+)\b",
        s,
        re.IGNORECASE,
    )
    if not m:
        return None
    ref = m.group(1).strip()
    return f"SELECT * FROM {ref} LIMIT {_DELETE_PREVIEW_ROW_CAP}"


def alter_sql_to_select_preview(alter_sql: str) -> Optional[str]:
    """Map ALTER TABLE ... to bounded SELECT * on that table (current rows)."""
    s = strip_sql_fences((alter_sql or "").strip().rstrip(";"))
    if ";" in s:
        return None
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+(?:ONLY\s+)?([`\"\w.]+)\b",
        s,
        re.IGNORECASE,
    )
    if not m:
        return None
    ref = m.group(1).strip()
    return f"SELECT * FROM {ref} LIMIT {_DELETE_PREVIEW_ROW_CAP}"


def create_table_as_select_preview_sql(create_sql: str) -> Optional[str]:
    """If CREATE TABLE ... AS (SELECT ...), return read-only SELECT with LIMIT."""
    s = strip_sql_fences((create_sql or "").strip().rstrip(";"))
    if ";" in s:
        return None
    m = re.search(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\w.]+\s+AS\s+",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    rest = s[m.end() :].strip()
    rm = re.match(r"^\(\s*(SELECT[\s\S]+)\)\s*$", rest, re.IGNORECASE | re.DOTALL)
    if rm:
        sel = rm.group(1).strip().rstrip(";")
    elif rest.upper().startswith("SELECT"):
        sel = rest.rstrip(";")
    else:
        return None
    if ";" in sel:
        return None
    if "LIMIT" not in sel.upper():
        sel = f"{sel} LIMIT {_DELETE_PREVIEW_ROW_CAP}"
    return sel


def insert_into_select_preview_sql(insert_sql: str) -> Optional[str]:
    """If INSERT INTO ... SELECT ..., return the SELECT (read-only) with LIMIT."""
    s = strip_sql_fences((insert_sql or "").strip().rstrip(";"))
    if ";" in s or not re.search(r"\bINSERT\s+INTO\s+", s, re.IGNORECASE):
        return None
    m = re.search(r"\bSELECT\b", s, re.IGNORECASE)
    if not m:
        return None
    sel = s[m.start() :].strip().rstrip(";")
    if ";" in sel:
        return None
    if "LIMIT" not in sel.upper():
        sel = f"{sel} LIMIT {_DELETE_PREVIEW_ROW_CAP}"
    return sel


def insert_sql_review_markdown(insert_sql: str) -> str:
    """Fallback: static review + raw VALUES when structured parse fails."""
    s = strip_sql_fences((insert_sql or "").strip())
    tm = re.search(r"INSERT\s+INTO\s+([`\"\w.]+)", s, re.IGNORECASE)
    table = f"`{tm.group(1)}`" if tm else "the target table"
    vm = re.search(r"\bVALUES\s+([\s\S]+?)(?:;)?\s*$", s, re.IGNORECASE)
    block = ""
    if vm:
        vals = vm.group(1).strip()
        if len(vals) > 4000:
            vals = vals[:4000] + "\n…"
        block = f"\n\n**VALUES clause (may be truncated):**\n\n```\n{vals}\n```"
    return (
        f"**Insert into {table} (review)**\n\n"
        "Confirm table name, column list, and values match what you intend before executing."
        + block
    )


def strip_insert_trailing_clauses(values_blob: str) -> str:
    """Remove ON CONFLICT / RETURNING after VALUES(...) list."""
    s = values_blob.strip().rstrip(";").strip()
    upper = s.upper()
    for key in (" ON CONFLICT", " RETURNING"):
        i = upper.find(key)
        if i != -1:
            s = s[:i].rstrip()
            upper = s.upper()
    return s.strip()


def split_sql_top_level_commas(inner: str) -> list[str]:
    """Split comma-separated SQL scalar expressions (respects quotes and nested parens)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(inner)
    in_squote = False
    in_dquote = False
    while i < n:
        c = inner[i]
        if in_squote:
            buf.append(c)
            if c == "'" and i + 1 < n and inner[i + 1] == "'":
                buf.append(inner[i + 1])
                i += 2
                continue
            if c == "'":
                in_squote = False
            i += 1
            continue
        if in_dquote:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(inner[i + 1])
                i += 2
                continue
            if c == '"':
                in_dquote = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            buf.append(c)
        elif c == '"':
            in_dquote = True
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return parts


def extract_insert_value_row_inners(values_blob: str) -> list[str]:
    """Return inner text of each top-level ( ... ) in a VALUES clause."""
    s = strip_insert_trailing_clauses(values_blob)
    rows: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        if s[i] != "(":
            break
        depth = 0
        in_squote = False
        in_dquote = False
        j = i
        while j < n:
            c = s[j]
            if in_squote:
                if c == "'" and j + 1 < n and s[j + 1] == "'":
                    j += 2
                    continue
                if c == "'":
                    in_squote = False
                j += 1
                continue
            if in_dquote:
                if c == '"':
                    in_dquote = False
                j += 1
                continue
            if c == "'":
                in_squote = True
                j += 1
                continue
            if c == '"':
                in_dquote = True
                j += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    rows.append(s[i + 1 : j])
                    j += 1
                    while j < n and s[j].isspace():
                        j += 1
                    if j < n and s[j] == ",":
                        j += 1
                    i = j
                    break
                if depth < 0:
                    return rows
            j += 1
        else:
            break
    return rows


def parse_insert_table_columns_values(insert_sql: str) -> Optional[tuple[str, Optional[list[str]], str]]:
    """Parse ``INSERT INTO tbl [(cols)] VALUES ...``.

    Returns (table_name, column_names or None, values_blob after VALUES).
    """
    s = strip_sql_fences((insert_sql or "").strip()).rstrip(";").strip()
    m = re.match(
        r"^\s*INSERT\s+INTO\s+([`\"\w.]+)\s+"
        r"(?:\(([^)]+)\)\s+)?VALUES\s+",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    table = m.group(1).strip().strip('`"')
    col_blob = m.group(2)
    columns: Optional[list[str]] = None
    if col_blob is not None and col_blob.strip():
        columns = [c.strip().strip('`"') for c in re.split(r"\s*,\s*", col_blob.strip()) if c.strip()]
    rest = s[m.end() :]
    if not rest.strip():
        return None
    return (table, columns, rest)


def parse_describe_table_column_names(describe_text: str) -> list[str]:
    """Extract ordered column names from MCP ``describe_table`` text output."""
    names: list[str] = []
    for line in (describe_text or "").splitlines():
        mm = re.match(r"^\s*-\s*([^:]+):", line)
        if mm:
            names.append(mm.group(1).strip())
    return names


def markdown_table_from_rows(headers: list[str], rows: list[list[str]]) -> str:
    """GitHub-flavored markdown table."""

    def esc(cell: str) -> str:
        t = (cell or "").replace("\n", " ").strip()
        if len(t) > _INSERT_PREVIEW_CELL_MAX:
            t = t[: _INSERT_PREVIEW_CELL_MAX] + "…"
        return t.replace("|", "\\|")

    if not headers:
        return ""
    head = "| " + " | ".join(esc(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines: list[str] = []
    for row in rows:
        padded = list(row[: len(headers)])
        while len(padded) < len(headers):
            padded.append("")
        body_lines.append("| " + " | ".join(esc(c) for c in padded) + " |")
    return "\n".join([head, sep] + body_lines)


def build_insert_values_markdown(
    table: str,
    explicit_cols: Optional[list[str]],
    values_blob: str,
    schema_column_order: Optional[list[str]],
) -> Optional[str]:
    """Build markdown table: column headers + one row per VALUES tuple."""
    inners = extract_insert_value_row_inners(values_blob)
    if not inners:
        return None
    row_cells = [
        split_sql_top_level_commas(inner) for inner in inners
    ]
    total_rows = len(inners)
    row_cells = row_cells[:_INSERT_PREVIEW_MAX_ROWS]
    max_w = max((len(r) for r in row_cells), default=0)
    if max_w == 0:
        return None

    if explicit_cols:
        ncol = max(len(explicit_cols), max_w)
        headers = list(explicit_cols)
        while len(headers) < ncol:
            headers.append(f"value_{len(headers) + 1}")
        headers = headers[:ncol]
    elif schema_column_order:
        ncol = max(len(schema_column_order), max_w)
        headers = list(schema_column_order)
        while len(headers) < ncol:
            headers.append(f"value_{len(headers) + 1}")
        headers = headers[:ncol]
    else:
        ncol = max_w
        headers = [f"column_{i + 1}" for i in range(ncol)]

    table_md = markdown_table_from_rows(headers, row_cells)
    if not table_md:
        return None
    extra = ""
    if total_rows > _INSERT_PREVIEW_MAX_ROWS:
        extra = f"\n\n_Showing first {_INSERT_PREVIEW_MAX_ROWS} of {total_rows} row(s)._"
    return (
        f"**Rows to insert into `{table}` (preview)**\n\n"
        f"{table_md}"
        f"{extra}"
    )


def preview_cell_for_table(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    s = s.replace("\n", " ").strip()
    if len(s) > _INSERT_PREVIEW_CELL_MAX:
        s = s[:_INSERT_PREVIEW_CELL_MAX] + "…"
    return s.replace("|", "\\|")


def json_query_rows_to_markdown_table(text: str) -> Optional[str]:
    """Turn ``execute_query`` JSON (array of objects) into a GFM markdown table."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return None
    if not all(isinstance(row, dict) for row in data):
        return None
    keys: List[str] = []
    seen: set[str] = set()
    for row in data:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                keys.append(str(k))
    if not keys:
        return None
    row_cells = [
        [preview_cell_for_table(row.get(k)) for k in keys]
        for row in data[:_DELETE_PREVIEW_ROW_CAP]
    ]
    return markdown_table_from_rows(keys, row_cells)


def is_execute_query_error_response(text: str) -> bool:
    """True when MCP ``execute_query`` returned an error string instead of rows."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.startswith("error executing"):
        return True
    if "does not exist" in t or "doesn't exist" in t:
        return True
    if "no such table" in t:
        return True
    if "unknown table" in t or "undefinedtable" in t.replace(" ", ""):
        return True
    if "operationalerror" in t:
        return True
    if "syntax error" in t:
        return True
    return False


def friendly_mutation_preview_error(raw: str) -> str:
    """Short user-facing message when preview SELECT fails (e.g. missing table/column)."""
    r = (raw or "").strip()
    low = r.lower()
    # Distinguish column errors from table errors — PostgreSQL uses "does not exist" for both.
    if "column" in low and "does not exist" in low:
        return (
            "**Column not found** in the table (or the column name is misspelled). "
            "Please check the column name in the SQL statement.\n\n"
            f"Details: {r[:400]}"
        )
    if "does not exist" in low or "no such table" in low or "unknown table" in low:
        return (
            "**Table does not exist** in the connected database (or the name is misspelled). "
            "Please create the table or check the spelling before modifying data."
        )
    if "syntax error" in low:
        return (
            "**SQL syntax error** in the preview query.\n\n"
            f"Details: {r[:400]}"
        )
    return (
        "**Không thể tải preview** (truy vấn đọc thất bại).\n\n"
        f"{r[:800]}"
    )


def format_mutation_preview_markdown(title: str, raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return f"**{title}**\n\n_No matching rows (empty preview)._"
    md_table = json_query_rows_to_markdown_table(text)
    if md_table:
        extra = ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > _DELETE_PREVIEW_ROW_CAP:
                extra = f"\n\n_Showing first {_DELETE_PREVIEW_ROW_CAP} of {len(parsed)} row(s)._"
        except json.JSONDecodeError:
            pass
        return f"**{title}**\n\n{md_table}{extra}"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and "|" in lines[0]:
        return f"**{title}**\n\n" + "\n".join(lines[: _DELETE_PREVIEW_ROW_CAP + 15])
    return f"**{title}**\n\n```\n{text[:12000]}\n```"


async def insert_values_preview_markdown(agent, insert_sql: str, _call_tool) -> str:
    """INSERT ... VALUES → markdown table with column headers (from SQL or ``describe_table``).

    Args:
        agent: The agent instance to call tools
        insert_sql: The INSERT SQL statement
        _call_tool: Callable to call MCP tool (agent.call_tool or similar)
    """
    parsed = parse_insert_table_columns_values(insert_sql)
    if not parsed:
        return insert_sql_review_markdown(insert_sql)
    table, explicit_cols, values_blob = parsed
    schema_order: Optional[list[str]] = None
    if not explicit_cols:
        try:
            raw = await _call_tool(agent, "describe_table", {"table_name": table})
            schema_order = parse_describe_table_column_names(raw) or None
        except Exception:
            pass
    md = build_insert_values_markdown(
        table, explicit_cols, values_blob, schema_order
    )
    return md if md else insert_sql_review_markdown(insert_sql)
