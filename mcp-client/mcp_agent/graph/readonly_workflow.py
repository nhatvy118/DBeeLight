"""Read-only database workflow - SELECT queries without approval step."""

import json
import logging
import re
from typing import Dict, Any

from openai import OpenAI
from langgraph.graph import END, StateGraph

from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import StageType

logger = logging.getLogger(__name__)


def _sqlite_table_names_from_attached_context(msg: str) -> list[str]:
    """Parse ``table: `name``` lines from RAG context (when present)."""
    if not msg or "AVAILABLE SQLITE TABLES" not in msg:
        return []
    return re.findall(r"table:\s*`([^`]+)`", msg)


def _session_file_tables_from_hint_block(msg: str) -> list[tuple[str, str]]:
    """Parse ``[SESSION FILE TABLES...]`` block injected for DB+file mode.

    Returns list of (filename, table_name) pairs.
    Example line: ``  - file: 50 product categories.csv  →  sqlite table: `t_50_...` ``
    """
    if not msg or "[SESSION FILE TABLES" not in msg:
        return []
    pairs: list[tuple[str, str]] = []
    for m in re.finditer(r"file:\s*(.+?)\s*→\s*sqlite table:\s*`([^`]+)`", msg):
        fname = m.group(1).strip()
        tname = m.group(2).strip()
        if tname:
            pairs.append((fname, tname))
    return pairs


def _parse_table_names_from_list_tools(text: str) -> list[str]:
    """Parse MCP ``list_tables`` text like ``Tables in database: a, b``."""
    s = (text or "").strip()
    if not s:
        return []
    m = re.search(r"tables?\s+in\s+database:\s*(.+?)(?:\n|$)", s, re.I | re.DOTALL)
    if not m:
        return []
    rest = m.group(1).strip()
    return [t.strip() for t in re.split(r"[\s,]+", rest) if t.strip()]


def _user_message_tail(msg: str) -> str:
    """The real user turn after RAG (``chat_usecase`` wraps as ``USER MESSAGE:``)."""
    m = re.search(r"(?is)\bUSER MESSAGE:\s*(.*)\Z", msg or "")
    if m:
        return (m.group(1) or "").strip()
    return (msg or "").strip()


def _sqlite_table_tokens_ordered_by_last_mention(text: str, actual_set: set[str]) -> list[str]:
    """``t_*`` tokens that exist in the DB, ordered by last mention (user cite is usually last in prompt)."""
    hits: dict[str, int] = {}
    for m in re.finditer(r"\bt_[A-Za-z0-9_]+\b", text or ""):
        name = m.group(0)
        if name in actual_set:
            hits[name] = m.start()
    if not hits:
        return []
    return [k for k, _ in sorted(hits.items(), key=lambda kv: -kv[1])]


def _prioritize_tables_from_user_message(
    user_message: str,
    candidate_tables: list[str],
    actual_tables: list[str],
) -> list[str]:
    """Prefer ``t_*`` names the user typed that exist in the DB (esp. after ``USER MESSAGE:``).

    RAG blocks often list a different imported table first (e.g. filename-based vs Sheet1);
    the LLM can merge that ahead of the table the user actually named.
    """
    actual_set = set(actual_tables)
    stripped_candidates = [str(t).strip() for t in candidate_tables if str(t).strip()]

    tail = _user_message_tail(user_message)
    ordered = _sqlite_table_tokens_ordered_by_last_mention(tail, actual_set)
    if ordered:
        return ordered
    ordered = _sqlite_table_tokens_ordered_by_last_mention(user_message or "", actual_set)
    if ordered:
        return ordered
    return stripped_candidates


def _parse_export_row_range(text: str) -> tuple[int, int] | None:
    """If the user asks for a 1-based inclusive row slice, return (limit, offset).

    Example: "rows 10 to 20" → limit 11, offset 9.
    """
    if not (text or "").strip():
        return None
    s = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .lower()
    )
    patterns = (
        r"rows?\s+(\d+)\s*(?:to|through|until|tới|đến|-|–)\s*(\d+)",
        r"(?:row|rows)\s*(?:#|n[oọ]?\s*)?(\d+)\s*(?:to|through|đến|tới|-|–)\s*(\d+)",
        r"d[oò]ng\s+(\d+)\s*(?:đến|tới|to|-|–)\s*(\d+)",
        r"line\s+(\d+)\s*(?:to|through|-|–)\s*(\d+)",
        # "between row 10 and 20"
        r"between\s+row\s+(\d+)\s+and\s+(\d+)",
        r"from\s+row\s+(\d+)\s+to\s+(\d+)",
    )
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= b:
                return (b - a + 1, a - 1)
    return None


def _export_slice_text_for_parsing(state: AgentState, effective_message: str, user_message: str) -> str:
    """Prefer USER MESSAGE tail and orchestrator ``nl_query`` so row numbers are not lost in RAG."""
    oi = state.get("orchestrator_intent") if isinstance(state.get("orchestrator_intent"), dict) else {}
    nl = str((oi or {}).get("nl_query") or "").strip()
    tail = _user_message_tail(user_message)
    parts = [tail, nl, effective_message, user_message]
    return " ".join(p for p in parts if p)


def _looks_schema_or_columns_question(text: str) -> bool:
    """True when the user asks for columns, fields, or table structure (not row data)."""
    q = (text or "").lower()
    phrases = (
        "column name",
        "column names",
        "list column",
        "list columns",
        "what column",
        "what columns",
        "which column",
        "fields in",
        "field names",
        "list of fields",
        "schema",
        "structure of the table",
        "structure of table",
        "table structure",
        "describe the table",
        "describe table",
        "show columns",
        "table columns",
    )
    if any(p in q for p in phrases):
        return True
    return False


# Nodes
async def intent_parse(state: AgentState, llm, agent) -> AgentState:
    """Parse user intent and determine operation type."""
    # Handle resume: user_message may not be in checkpoint state
    intent_data = state.get("intent") or {}
    user_message = state.get("user_message") or str(intent_data.get("resolved_query") or "")
    logger.info(f"[ReadOnly] Intent parse: {user_message[:50]}...")
    recent_context = await _get_recent_session_context(agent)

    response = llm.chat.completions.create(
        model="gpt-5.2",
        messages=[
            {
                "role": "system",
                "content": """Analyze the database request and extract:
- operation: SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, EXPORT, LIST_TABLES, DESCRIBE_TABLE, CONNECT, DISCONNECT, UNKNOWN
  Use **LIST_TABLES** when the user wants to see, list, show, count, or discover what tables exist (e.g. "show me all tables", "list tables", "how many tables", "what tables are there", "which tables", "display all tables", "liệt kê bảng", "bao nhiêu bảng"). Do NOT generate SQL for this — just use LIST_TABLES.
  Use **DESCRIBE_TABLE** when the user wants to see the structure/schema/columns of a specific table.
  Use **EXPORT** (not SELECT) ONLY when the user explicitly asks to download, save, or export data as a file (e.g. "export to Excel", "download as xlsx", "save to csv", "export rows 10-20").
  Do NOT use EXPORT just because the user message contains an uploaded file marker or mentions reading/querying data from an uploaded file — that is SELECT.
  Use **CONNECT** when the user asks to connect to a database. Use **DISCONNECT** when the user asks to disconnect.
- tables: list of every table name referenced (required for ALTER/INSERT/UPDATE/DELETE/DROP/SELECT), e.g. "add column to table bicycle" -> ["bicycle"]
- filters: WHERE conditions
- exports: if user wants to export to Excel
- resolved_query: rewrite latest user message into a self-contained request by resolving context references.
  **Preserve** row numbers and ranges for exports (e.g. "rows 10 to 20", "10-20") verbatim — do not drop them.

Return JSON."""
            },
            {
                "role": "user",
                "content": (
                    f"Latest user message: {user_message}\n\n"
                    f"Recent conversation context:\n{recent_context or '(none)'}"
                ),
            }
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )

    try:
        intent = json.loads(response.choices[0].message.content)
    except Exception:
        intent = {}

    operation = str(intent.get("operation", "SELECT")).strip().upper()
    resolved_query = str(intent.get("resolved_query") or user_message).strip() or user_message

    safe_intent = {
        "operation": operation,
        "tables": intent.get("tables", []),
        "filters": intent.get("filters", {}),
        "resolved_query": resolved_query,
    }
    raw_um = str(state.get("user_message") or "")
    from_ctx = _sqlite_table_names_from_attached_context(raw_um)
    merged_tables: list = list(safe_intent.get("tables") or [])
    for t in from_ctx:
        if t and t not in merged_tables:
            merged_tables.append(t)

    # If the orchestrator injected an authoritative table_hint from the UI data-source selector,
    # use it as the definitive table list (overrides LLM-extracted tables and context markers).
    orch_intent = state.get("orchestrator_intent")
    forced_table_hint = str((orch_intent or {}).get("table_hint") or "").strip() if isinstance(orch_intent, dict) else ""
    if forced_table_hint:
        forced_tables = [t.strip() for t in forced_table_hint.split(",") if t.strip()]
        if forced_tables:
            merged_tables = forced_tables
            logger.info("[ReadOnly] orchestrator table_hint overrides merged_tables → %s", merged_tables)

    safe_intent["tables"] = merged_tables

    logger.info("[ReadOnly] Parsed operation=%s", operation)

    return {
        **state,
        "intent": safe_intent,
        "followup_context": recent_context,
    }


async def schema_discovery(state: AgentState, llm, agent) -> AgentState:
    """Discover schema for relevant tables - skip for CREATE."""
    tables = list((state.get("intent") or {}).get("tables") or [])
    logger.info(f"[ReadOnly] Schema discovery for: {tables}")

    if not agent:
        return {**state, "table_schema": {}}

    log_lines: list[str] = []
    op = str((state.get("intent") or {}).get("operation", "SELECT")).strip().upper()

    tables_result = ""
    try:
        tables_result = await _call_tool(agent, "list_tables", {})
        log_lines.append(f"list_tables: {tables_result}")
    except Exception as e:
        log_lines.append(f"list_tables error: {e}")

    actual_tables = _parse_table_names_from_list_tools(tables_result)

    # CREATE targets a new table — names in intent often do not exist yet; skip existence check.
    if op == "CREATE":
        log_block = "\n".join(log_lines)
        logger.info(f"[ReadOnly] Schema discovery response: {log_block[:500]}...")
        return {
            **state,
            "table_schema": {"tables": tables, "all_tables": list(actual_tables)},
        }

    # Uploaded session DB often has exactly one real table; user may say "user" or omit name.
    tables_work: list[str] = [str(t).strip() for t in tables if str(t).strip()]
    um = str(state.get("user_message") or "")
    if actual_tables:
        tables_work = _prioritize_tables_from_user_message(um, tables_work, actual_tables)
    if not tables_work and len(actual_tables) == 1:
        tables_work = list(actual_tables)
        log_lines.append(f"[fallback] no table hint → using sole DB table `{tables_work[0]}`")

    missing: list[str] = []
    for t in tables_work:
        name = str(t).strip()
        if not name:
            continue
        try:
            d = await _call_tool(agent, "describe_table", {"table_name": name})
            log_lines.append(f"describe_table({name}): {d}")
            if not _describe_table_succeeded(d):
                missing.append(name)
        except Exception as e:
            log_lines.append(f"describe_table({name}) error: {e}")
            missing.append(name)

    # Wrong hint (e.g. ``user``) but only one physical table — use it for the rest of the turn.
    if missing and len(actual_tables) == 1:
        only = actual_tables[0]
        try:
            d = await _call_tool(agent, "describe_table", {"table_name": only})
            log_lines.append(f"describe_table({only}) [hint-mismatch fallback]: {d}")
            if _describe_table_succeeded(d):
                missing = []
                tables_work = [only]
        except Exception as e:
            log_lines.append(f"describe_table fallback error: {e}")

    log_block = "\n".join(log_lines)
    logger.info(f"[ReadOnly] Schema discovery response: {log_block[:500]}...")

    if missing:
        miss_fmt = ", ".join(f"{m}" for m in missing)
        msg = (
            f"**Unknown table(s):** {miss_fmt}\n\n"
            "Those tables are not in the connected database. "
            "Fix the table name or create the table before continuing.\n\n"
            "**Discovery log:**\n\n```\n"
            f"{log_block[:8000]}\n```"
        )
        return {
            **state,
            "schema_discovery_failed": True,
            "error": f"Table(s) not found: {', '.join(missing)}",
            "output": {
                "type": "error",
                "message": msg,
            },
            "table_schema": {"tables": tables_work, "missing": missing, "all_tables": list(actual_tables)},
        }

    intent_patch = {**(state.get("intent") or {}), "tables": tables_work}
    return {
        **state,
        "intent": intent_patch,
        "table_schema": {"tables": tables_work, "all_tables": list(actual_tables)},
    }


async def query_execution(state: AgentState, llm, agent) -> AgentState:
    """Execute SELECT query directly - no approval needed for read-only."""
    if state.get("schema_discovery_failed"):
        # Graph always runs this node after SCHEMA_DISCOVERY; do not overwrite the error output.
        return state

    intent = state.get("intent", {})
    user_message = state["user_message"]
    effective_message = str(intent.get("resolved_query") or user_message)
    operation = intent.get("operation", "SELECT").upper()
    logger.info(f"[ReadOnly] Query execution for: {operation}")

    # Safety net if intent_parse still left UNKNOWN (e.g. table list populated only after merge).
    if operation == "UNKNOWN":
        combined = f"{effective_message} {user_message}"
        if _looks_schema_or_columns_question(combined):
            tables = (state.get("table_schema") or {}).get("tables") or intent.get("tables") or []
            if tables and agent:
                table_name = str(tables[0]).strip()
                if table_name:
                    try:
                        desc = await _call_tool(agent, "describe_table", {"table_name": table_name})
                        return {
                            **state,
                            "sql": None,
                            "query_result": desc,
                            "output": {
                                "type": "query_result",
                                "data": desc,
                                "message": desc,
                            },
                        }
                    except Exception as e:
                        logger.warning("[ReadOnly] UNKNOWN→describe_table fallback failed: %s", e)

    # Safe DB metadata/connect tools — prefer direct MCP calls when we already know the table
    # (avoids process_query failing on long RAG-prefixed user_message).
    _SAFE_DB_TOOL_OPERATIONS = frozenset(
        {"LIST_TABLES", "DESCRIBE_TABLE"}
    )
    if operation in _SAFE_DB_TOOL_OPERATIONS:
        if not agent:
            return {
                **state,
                "sql": None,
                "query_result": None,
                "output": {
                    "type": "error",
                    "message": "No agent available to execute safe DB tools.",
                },
            }
        if operation == "DESCRIBE_TABLE":
            tables = (state.get("table_schema") or {}).get("tables") or intent.get("tables") or []
            if tables:
                table_name = str(tables[0]).strip()
                if table_name:
                    try:
                        desc = await _call_tool(agent, "describe_table", {"table_name": table_name})
                        return {
                            **state,
                            "sql": None,
                            "query_result": desc,
                            "output": {
                                "type": "query_result",
                                "data": desc,
                                "message": desc,
                            },
                        }
                    except Exception as e:
                        logger.warning("[ReadOnly] describe_table direct call failed: %s", e)
        if operation == "LIST_TABLES":
            try:
                lt = await _call_tool(agent, "list_tables", {})
                return {
                    **state,
                    "sql": None,
                    "query_result": lt,
                    "output": {
                        "type": "query_result",
                        "data": lt,
                        "message": lt,
                    },
                }
            except Exception as e:
                logger.warning("[ReadOnly] list_tables direct call failed: %s", e)
        response = await agent.process_query(
            effective_message,
            verbose=False,
            persist_history=False,
        )
        return {
            **state,
            "sql": None,
            "query_result": response,
            "output": {
                "type": "query_result",
                "data": response,
                "message": response,
            },
        }

    # Connect/Disconnect — redirect user to UI button.
    if operation in {"CONNECT", "DISCONNECT"}:
        msg = (
            "To connect to a database, please use the **Connect Database** button in the side panel. "
            "Database connections are managed through the UI, not via chat."
        )
        return {
            **state,
            "sql": None,
            "query_result": msg,
            "output": {"type": "query_result", "data": msg, "message": msg},
        }

    # Export to Excel — must call MCP tool (do not fall through to SELECT + markdown table).
    if operation == "EXPORT":
        if not agent:
            return {
                **state,
                "output": {
                    "type": "error",
                    "message": "No agent available for Excel export.",
                },
            }
        tables = (state.get("table_schema") or {}).get("tables") or intent.get("tables") or []
        if not tables:
            return {
                **state,
                "output": {
                    "type": "error",
                    "message": "No table identified for export. Name the table or upload session data first.",
                },
            }
        table_name = str(tables[0]).strip()
        slice_q = _export_slice_text_for_parsing(state, effective_message, user_message)
        row_slice = _parse_export_row_range(slice_q)
        if row_slice:
            logger.info("[ReadOnly] EXPORT row slice limit=%s offset=%s", row_slice[0], row_slice[1])
        else:
            logger.info("[ReadOnly] EXPORT no row slice parsed from: %s", slice_q[:200])
        tool_args: Dict[str, Any] = {
            "table_name": table_name,
            "columns": "*",
            "where_clause": None,
        }
        if row_slice:
            tool_args["limit"], tool_args["offset"] = row_slice
        try:
            raw = await _call_tool(agent, "export_table_to_excel", tool_args)
        except Exception as e:
            logger.warning("[ReadOnly] export_table_to_excel failed: %s", e)
            return {
                **state,
                "output": {"type": "error", "message": f"Excel export failed: {e}"},
            }
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            payload = {"error": f"Invalid export response: {str(raw)[:500]}"}
        if not isinstance(payload, dict):
            return {
                **state,
                "output": {"type": "error", "message": "Export returned an unexpected shape."},
            }
        if payload.get("error"):
            return {
                **state,
                "output": {"type": "error", "message": str(payload["error"])},
            }
        b64 = payload.get("base64")
        fn = str(payload.get("filename") or f"{table_name}.xlsx")
        rc = payload.get("row_count", 0)
        if not b64:
            return {
                **state,
                "output": {"type": "error", "message": "Export returned no file data."},
            }
        msg = (
            f"Exported **{fn}** ({rc} rows).\n\n"
            f"[EXCEL_BASE64_START]\n{b64}\n[EXCEL_BASE64_END]\n"
            f"[FILENAME_START]\n{fn}\n[FILENAME_END]\n"
            f"[ROW_COUNT_START]\n{rc}\n[ROW_COUNT_END]"
        )
        return {
            **state,
            "sql": None,
            "query_result": msg,
            "output": {"type": "query_result", "data": msg, "message": msg},
        }

    # Schema/info requests should return table description.
    if operation in {"SELECT", "DESCRIBE_TABLE"}:
        ql = (effective_message + " " + str(user_message)).lower()
        schema_like = (
            "show info about table" in ql
            or "describe table" in ql
            or "table structure" in ql
            or "schema of table" in ql
            or "thông tin bảng" in ql
            or "mô tả bảng" in ql
            or "cấu trúc bảng" in ql
            or _looks_schema_or_columns_question(ql)
        )
        if schema_like and agent:
            tables = (state.get("table_schema") or {}).get("tables") or intent.get("tables") or []
            if tables:
                table_name = str(tables[0]).strip()
                if table_name:
                    desc = await _call_tool(agent, "describe_table", {"table_name": table_name})
                    return {
                        **state,
                        "sql": None,
                        "query_result": desc,
                        "output": {
                            "type": "query_result",
                            "data": desc,
                            "message": desc,
                        },
                    }

    # Generate and execute SELECT
    if agent:
        from mcp_agent.graph.database_utils import (
            strip_sql_fences,
            is_execute_query_error_response,
            json_query_rows_to_markdown_table,
            detect_db_type,
            get_select_system_prompt,
            extract_attached_files_context_block,
        )
        db_type = detect_db_type(agent)
        attached = extract_attached_files_context_block(user_message)
        messages = [{"role": "system", "content": get_select_system_prompt(db_type)}]

        # --- Allowed tables injection ---
        # all_tables: every table returned by list_tables during schema_discovery.
        # Stored inside table_schema to avoid extra top-level state fields.
        all_db_tables: list[str] = [
            str(t).strip()
            for t in ((state.get("table_schema") or {}).get("all_tables") or [])
            if str(t).strip()
        ]

        # session_file_pairs: (filename, table_name) from [SESSION FILE TABLES] block (DB+file mode).
        session_file_pairs = _session_file_tables_from_hint_block(user_message)
        session_file_table_names = {tname for _, tname in session_file_pairs}

        # Split all_db_tables into primary-DB tables and session-file tables.
        primary_db_tables = [t for t in all_db_tables if t not in session_file_table_names and not t.startswith("t_")]
        # session file tables already in all_db_tables (via list_tables filter).
        session_tables_in_db = [t for t in all_db_tables if t.startswith("t_")]

        # Build constraint block whenever we have any table info.
        if all_db_tables or session_file_pairs:
            constraint_lines: list[str] = [
                "ALLOWED TABLES — your SQL MUST reference ONLY the table names listed below.",
                "Do NOT use information_schema, pg_catalog, pg_tables, sqlite_master,",
                "  or ANY system/metadata tables — even to count tables.",
                "Do NOT use filenames or invented names as table identifiers.",
                "To answer 'how many tables': count the entries in this list, do not query system tables.",
                "",
            ]
            if primary_db_tables:
                constraint_lines.append("Primary database tables:")
                for t in primary_db_tables:
                    constraint_lines.append(f"  - `{t}`")
                constraint_lines.append("")
            # Session file tables — show with filename hint when available.
            session_tname_to_fname = {tname: fname for fname, tname in session_file_pairs}
            all_session_tables = list(dict.fromkeys(session_tables_in_db + list(session_file_table_names)))
            if all_session_tables:
                constraint_lines.append("Session-file tables (use these EXACT identifiers):")
                for t in all_session_tables:
                    fname_hint = session_tname_to_fname.get(t, "")
                    suffix = f"  ← from file: {fname_hint}" if fname_hint else ""
                    constraint_lines.append(f"  - `{t}`{suffix}")
            messages.append({"role": "system", "content": "\n".join(constraint_lines)})

        if attached:
            messages.append({"role": "system", "content": attached})
        messages.append({"role": "user", "content": effective_message})
        sel_resp = llm.chat.completions.create(
            model="gpt-5.2",
            messages=messages,
            temperature=0,
        )
        select_sql = strip_sql_fences(sel_resp.choices[0].message.content or "")
        try:
            query_result = await _call_tool(agent, "execute_query", {"query": select_sql})
        except Exception as e:
            query_result = f"Error executing SELECT: {e}"

        # Keep SQL block unchanged, and format result for better markdown rendering:
        # - JSON rows -> markdown table
        # - non-JSON / parse-fail -> fenced text block (avoid long inline text)
        result_markdown = json_query_rows_to_markdown_table(query_result)
        rendered_result = result_markdown if result_markdown else f"```text\n{query_result}\n```"

        response = (
            f"```sql\n{select_sql}\n```\n\n"
            f"{rendered_result}"
        )
        output_type = "error" if is_execute_query_error_response(query_result) else "query_result"
        return {
            **state,
            "sql": select_sql,
            "query_result": response,
            "output": {"type": output_type, "data": response, "message": response}
        }

    return {
        **state,
        "output": {"type": "error", "message": "No agent available for query execution"},
    }


async def _get_recent_session_context(agent, limit: int = 6) -> str:
    """Get recent user/assistant messages for follow-up disambiguation."""
    if not agent or not getattr(agent, "session_manager", None):
        return ""
    try:
        msgs = await agent.session_manager.get_llm_context_messages()
    except Exception:
        return ""
    if not isinstance(msgs, list) or not msgs:
        return ""
    lines: list[str] = []
    for m in msgs[-limit:]:
        role = str((m or {}).get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str((m or {}).get("content") or "").strip()
        if not content:
            continue
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _describe_table_succeeded(describe_text: str) -> bool:
    """False when MCP reports missing table or hard error."""
    s = (describe_text or "").strip().lower()
    if not s:
        return False
    if "not found" in s:
        return False
    if s.startswith("error "):
        return False
    return True


async def _call_tool(agent, tool_name: str, args: dict) -> str:
    """Call MCP tool directly through agent sessions."""
    if not agent:
        raise RuntimeError("No agent available")

    for _server_name, session in agent.sessions.items():
        try:
            result = await session.call_tool(tool_name, args)
            content = result.content
            if hasattr(content, "text"):
                return str(content.text)
            if isinstance(content, list) and content:
                first = content[0]
                if hasattr(first, "text"):
                    return str(first.text)
            return str(content)
        except Exception:
            continue

    raise RuntimeError(f"Tool '{tool_name}' not found in connected sessions")


class ReadOnlyWorkflow:
    """Read-only database workflow for SELECT queries.

    Nodes:
    1. INTENT_PARSE - classify operation
    2. SCHEMA_DISCOVERY - verify tables exist
    3. QUERY_EXECUTION - run SELECT directly (no approval)

    Flow: START → INTENT_PARSE → SCHEMA_DISCOVERY → QUERY_EXECUTION → DONE
    """

    def __init__(self, llm=None, agent=None):
        self.llm = llm or OpenAI()
        self.agent = agent

    def _build_graph(self) -> Any:
        """Build LangGraph for read-only workflow."""
        workflow = StateGraph(AgentState)

        async def intent_parse_node(state):
            return await intent_parse(state, self.llm, self.agent)

        async def schema_discovery_node(state):
            return await schema_discovery(state, self.llm, self.agent)

        async def query_execution_node(state):
            return await query_execution(state, self.llm, self.agent)

        async def done_handler(state):
            return {**state, "current_stage": StageType.DONE.value}

        workflow.add_node("INTENT_PARSE", intent_parse_node)
        workflow.add_node("SCHEMA_DISCOVERY", schema_discovery_node)
        workflow.add_node("QUERY_EXECUTION", query_execution_node)
        workflow.add_node(StageType.DONE.value, done_handler)

        workflow.set_entry_point("INTENT_PARSE")
        workflow.add_edge("INTENT_PARSE", "SCHEMA_DISCOVERY")
        workflow.add_edge("SCHEMA_DISCOVERY", "QUERY_EXECUTION")
        workflow.add_edge("QUERY_EXECUTION", StageType.DONE.value)
        workflow.add_edge(StageType.DONE.value, END)

        return workflow.compile()

    async def run(
        self,
        session_id: str,
        user_message: str,
        *,
        orchestrator_intent: Dict[str, Any] | None = None,
    ) -> AgentState:
        """Run the read-only workflow.

        ``orchestrator_intent``: ``IntentResult``-style dict (e.g. ``nl_query``) from the top-level
        router — used so EXPORT row ranges are not dropped by inner ``resolved_query`` rewriting.
        """
        state: AgentState = create_initial_state(session_id, user_message, "database")
        if orchestrator_intent:
            state = {**state, "orchestrator_intent": orchestrator_intent}
        graph = self._build_graph()
        result = await graph.ainvoke(state)
        return result