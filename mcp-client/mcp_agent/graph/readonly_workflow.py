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


# Nodes
async def intent_parse(state: AgentState, llm, agent) -> AgentState:
    """Parse user intent and determine operation type."""
    # Handle resume: user_message may not be in checkpoint state
    intent_data = state.get("intent") or {}
    user_message = state.get("user_message") or str(intent_data.get("resolved_query") or "")
    logger.info(f"[ReadOnly] Intent parse: {user_message[:50]}...")
    recent_context = await _get_recent_session_context(agent)

    response = llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": """Analyze the database request and extract:
- operation: SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, EXPORT, LIST_TABLES, DESCRIBE_TABLE, CONNECT, DISCONNECT, UNKNOWN
- tables: list of every table name referenced (required for ALTER/INSERT/UPDATE/DELETE/DROP/SELECT), e.g. "add column to table bicycle" -> ["bicycle"]
- filters: WHERE conditions
- exports: if user wants to export to Excel
- detected_language: "en" by default. Use "vi" ONLY if the LATEST user message contains Vietnamese diacritics (à á ả ạ ă â đ ê ô ơ ư …) or unambiguous Vietnamese words ("bảng", "truy vấn", "kết nối", "danh sách"). Ignore conversation history. Short English-keyword queries like "list tables" → "en".
- resolved_query: rewrite latest user message into a self-contained request by resolving context references
- connection: object for CONNECT with keys host, port, database, username, password (use null if unknown)
- IMPORTANT: if operation is CONNECT, ALWAYS include `connection` with all five keys.

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
    rq_lower = resolved_query.lower()
    if operation == "SELECT":
        schema_like = (
            "show info about table" in rq_lower
            or "describe table" in rq_lower
            or "table structure" in rq_lower
            or "schema of table" in rq_lower
            or "thông tin bảng" in rq_lower
            or "mô tả bảng" in rq_lower
            or "cấu trúc bảng" in rq_lower
        )
        if schema_like:
            operation = "DESCRIBE_TABLE"
    operation_to_intent = {
        "SELECT": "select_query",
        "INSERT": "insert_data",
        "UPDATE": "update_data",
        "DELETE": "delete_data",
        "CREATE": "create_table",
        "ALTER": "alter_table",
        "DROP": "drop_table",
        "EXPORT": "export_data",
        "LIST_TABLES": "list_tables",
        "DESCRIBE_TABLE": "describe_table",
        "CONNECT": "connect_db",
        "DISCONNECT": "disconnect_db",
        "CONFIRM": "confirm_action",
    }
    derived_intent = operation_to_intent.get(operation, "unknown")

    safe_intent = {
        "operation": operation,
        "tables": intent.get("tables", []),
        "filters": intent.get("filters", {}),
        "exports": intent.get("exports", "no"),
        "detected_language": intent.get("detected_language", "en"),
        "derived_intent": derived_intent,
        "resolved_query": resolved_query,
        "connection": intent.get("connection", {}) if isinstance(intent.get("connection"), dict) else {},
    }
    if safe_intent["operation"] == "CONNECT":
        conn = safe_intent.get("connection") if isinstance(safe_intent.get("connection"), dict) else {}
        if not isinstance(conn, dict):
            conn = {}
        safe_intent["connection"] = {
            "host": conn.get("host"),
            "port": conn.get("port"),
            "database": conn.get("database"),
            "username": conn.get("username"),
            "password": conn.get("password"),
        }

    raw_um = str(state.get("user_message") or "")
    from_ctx = _sqlite_table_names_from_attached_context(raw_um)
    merged_tables: list = list(safe_intent.get("tables") or [])
    for t in from_ctx:
        if t and t not in merged_tables:
            merged_tables.append(t)
    safe_intent["tables"] = merged_tables

    logger.info(
        "[ReadOnly] Parsed operation=%s, derived_intent=%s, connection=%s",
        operation,
        derived_intent,
        safe_intent.get("connection"),
    )

    return {
        **state,
        "intent": safe_intent,
        "detected_language": safe_intent.get("detected_language", "en"),
        "tables": merged_tables,
        "followup_context": recent_context,
    }


async def schema_discovery(state: AgentState, llm, agent) -> AgentState:
    """Discover schema for relevant tables - skip for CREATE."""
    tables = state.get("tables", []) or []
    logger.info(f"[ReadOnly] Schema discovery for: {tables}")

    if not agent:
        return {**state, "table_schema": {}}

    log_lines: list[str] = []
    op = str((state.get("intent") or {}).get("operation", "SELECT")).strip().upper()

    try:
        tables_result = await _call_tool(agent, "list_tables", {})
        log_lines.append(f"list_tables: {tables_result}")
    except Exception as e:
        log_lines.append(f"list_tables error: {e}")

    # CREATE targets a new table — names in intent often do not exist yet; skip existence check.
    if op == "CREATE":
        log_block = "\n".join(log_lines)
        logger.info(f"[ReadOnly] Schema discovery response: {log_block[:500]}...")
        return {
            **state,
            "table_schema": {"tables": tables},
        }

    missing: list[str] = []
    for t in tables:
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
            "table_schema": {"tables": tables, "missing": missing},
        }

    return {
        **state,
        "table_schema": {"tables": tables},
    }


async def query_execution(state: AgentState, llm, agent) -> AgentState:
    """Execute SELECT query directly - no approval needed for read-only."""
    intent = state.get("intent", {})
    user_message = state["user_message"]
    effective_message = str(intent.get("resolved_query") or user_message)
    operation = intent.get("operation", "SELECT").upper()
    logger.info(f"[ReadOnly] Query execution for: {operation}")

    # Safe DB metadata/connect tools
    _SAFE_DB_TOOL_OPERATIONS = frozenset(
        {"LIST_TABLES", "DESCRIBE_TABLE", "CONNECT", "DISCONNECT"}
    )
    if operation in _SAFE_DB_TOOL_OPERATIONS:
        if agent:
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
        return {
            **state,
            "sql": None,
            "query_result": None,
            "output": {
                "type": "error",
                "message": "No agent available to execute safe DB tools.",
            },
        }

    # Schema/info requests should return table description.
    if operation in {"SELECT", "DESCRIBE_TABLE"}:
        ql = effective_message.lower()
        schema_like = (
            "show info about table" in ql
            or "describe table" in ql
            or "table structure" in ql
            or "schema of table" in ql
            or "thông tin bảng" in ql
            or "mô tả bảng" in ql
            or "cấu trúc bảng" in ql
        )
        if schema_like and agent:
            tables = state.get("tables", []) or intent.get("tables", []) or []
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
        if attached:
            messages.append({"role": "system", "content": attached})
        messages.append({"role": "user", "content": effective_message})
        sel_resp = llm.chat.completions.create(
            model="gpt-4o-mini",
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

    async def run(self, session_id: str, user_message: str) -> AgentState:
        """Run the read-only workflow."""
        state = create_initial_state(session_id, user_message, "database")
        graph = self._build_graph()
        result = await graph.ainvoke(state)
        return result