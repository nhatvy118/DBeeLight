"""Create table workflow - CREATE TABLE with schema preview and human approval."""

import json
import logging

from openai import OpenAI
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from mcp_agent.graph.langgraph_checkpointer import get_async_checkpointer
from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import StageType

logger = logging.getLogger(__name__)
GRAPH_INVOKE_VERSION = "v2"


def _is_rich_state(d: dict) -> bool:
    return bool(d.get("output")) or bool(d.get("current_stage")) or bool(d.get("session_id"))


def _extract_dict_candidate(obj) -> dict | None:
    if isinstance(obj, dict):
        return obj
    for attr in ("values", "value", "state"):
        nested = getattr(obj, attr, None)
        if isinstance(nested, dict):
            return nested
    try:
        model_dump = getattr(obj, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
    except Exception:
        pass
    return None


def _pick_best_state(candidates: list[dict]) -> AgentState:
    valid = [c for c in candidates if isinstance(c, dict) and c]
    if not valid:
        return {}
    rich = [c for c in valid if _is_rich_state(c)]
    pool = rich if rich else valid
    pool.sort(key=lambda x: len(x.keys()), reverse=True)
    return pool[0]


def _extract_resume_state_from_graph_output(raw) -> AgentState:
    """Best-effort extraction of full state from LangGraph GraphOutput."""
    candidates: list[dict] = []
    state_obj = getattr(raw, "state", None)
    if state_obj is not None:
        values = getattr(state_obj, "values", None)
        if isinstance(values, dict):
            candidates.append(values)
        nested = _extract_dict_candidate(state_obj)
        if isinstance(nested, dict):
            candidates.append(nested)
    for attr in ("value", "values", "result", "output"):
        extracted = _extract_dict_candidate(getattr(raw, attr, None))
        if isinstance(extracted, dict):
            candidates.append(extracted)
    extracted_raw = _extract_dict_candidate(raw)
    if isinstance(extracted_raw, dict):
        candidates.append(extracted_raw)
    return _pick_best_state(candidates)


def _normalize_graph_result(raw) -> AgentState:
    """Normalize LangGraph return value into AgentState dict."""
    candidates: list[dict] = []
    first = _extract_dict_candidate(raw)
    if isinstance(first, dict):
        candidates.append(first)
    for attr in ("value", "state", "values", "output", "result"):
        v = getattr(raw, attr, None)
        extracted = _extract_dict_candidate(v)
        if isinstance(extracted, dict):
            candidates.append(extracted)
    try:
        casted = dict(raw)
        if isinstance(casted, dict):
            candidates.append(casted)
    except Exception:
        pass
    return _pick_best_state(candidates)


async def _hydrate_from_checkpoint(graph, cfg, state: AgentState) -> AgentState:
    """Load latest persisted state when invoke result lacks workflow values."""
    if _is_rich_state(state):
        return state
    try:
        snap = await graph.aget_state(cfg)
        values = getattr(snap, "values", None)
        if isinstance(values, dict) and values and _is_rich_state(values):
            logger.info(
                "[CreateTable] Hydrated from checkpoint, keys=%s, stage=%s, output_type=%s",
                list(values.keys()),
                values.get("current_stage"),
                ((values.get("output") or {}).get("type") if isinstance(values.get("output"), dict) else None),
            )
            merged = dict(values)
            if "__interrupt__" in state:
                merged["__interrupt__"] = state["__interrupt__"]
            return merged
    except Exception:
        pass
    try:
        idx = 0
        async for hist in graph.aget_state_history(cfg):
            idx += 1
            values = getattr(hist, "values", None)
            if isinstance(values, dict) and values and _is_rich_state(values):
                logger.info(
                    "[CreateTable] Hydrated from history idx=%s, keys=%s, stage=%s, output_type=%s",
                    idx,
                    list(values.keys()),
                    values.get("current_stage"),
                    ((values.get("output") or {}).get("type") if isinstance(values.get("output"), dict) else None),
                )
                merged = dict(values)
                if "__interrupt__" in state:
                    merged["__interrupt__"] = state["__interrupt__"]
                return merged
            if idx >= 10:
                break
    except Exception:
        pass
    return state


async def _read_state_from_checkpoint(graph, cfg) -> AgentState:
    """Read authoritative workflow state after resume from checkpointer."""
    thread_id = (cfg.get("configurable") or {}).get("thread_id")
    fallback_cfg = {"configurable": {"thread_id": thread_id}} if thread_id else cfg
    try:
        snapshot = await graph.aget_state(cfg)
    except Exception as e:
        if "Subgraph" in str(e) and "not found" in str(e):
            logger.info("[CreateTable] aget_state with checkpoint_ns failed, retry thread-only")
            snapshot = await graph.aget_state(fallback_cfg)
        else:
            raise
    hydrated: AgentState = {}
    values = getattr(snapshot, "values", None) if snapshot else None
    if isinstance(values, dict) and values:
        hydrated = dict(values)

    # If graph paused again on a later interrupt, expose it for API/UI.
    tasks = getattr(snapshot, "tasks", None) if snapshot else None
    if isinstance(tasks, list):
        for t in tasks:
            interrupts = getattr(t, "interrupts", None)
            if interrupts:
                hydrated["__interrupt__"] = interrupts
                break
    return hydrated


async def intent_parse(state: AgentState, llm, agent) -> AgentState:
    """Parse user intent - always CREATE for this workflow."""
    # Handle resume: user_message may not be in checkpoint state
    intent_data = state.get("intent") or {}
    user_message = state.get("user_message") or str(intent_data.get("resolved_query") or "")
    logger.info(f"[CreateTable] Intent parse: {user_message[:50]}...")
    recent_context = await _get_recent_session_context(agent)

    response = llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": """Analyze the database request and extract:
- operation: CREATE, SELECT, INSERT, UPDATE, DELETE, etc.
- tables: list of every table name referenced
- detected_language: "en" by default. Use "vi" ONLY if the LATEST user message contains Vietnamese diacritics (à á ả ạ ă â đ ê ô ơ ư …) or unambiguous Vietnamese words ("bảng", "truy vấn", "kết nối", "danh sách"). Ignore conversation history. Short English-keyword queries like "list tables" → "en".
- resolved_query: rewrite latest user message into a self-contained request

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

    operation = str(intent.get("operation", "CREATE")).strip().upper()

    safe_intent = {
        "operation": operation,
        "tables": intent.get("tables", []),
        "detected_language": intent.get("detected_language", "en"),
        "resolved_query": str(intent.get("resolved_query") or user_message).strip(),
    }

    return {
        **state,
        "intent": safe_intent,
        "detected_language": safe_intent.get("detected_language", "en"),
        "followup_context": recent_context,
    }


async def schema_preview(state: AgentState, llm, agent) -> AgentState:
    """Generate CREATE TABLE schema for review."""
    user_message = state["user_message"]

    if not agent:
        return {**state, "wait_user": False}

    logger.info("[CreateTable] Schema preview")
    try:
        args = await _extract_create_table_args(llm, user_message)
        schema_response = await _call_tool(agent, "show_create_table_schema", args)
    except Exception as e:
        schema_response = _generate_create_table_clarification(
            llm=llm,
            user_message=user_message,
            detected_language=str(state.get("detected_language") or "en"),
            reason=str(e),
        )

    tables = list((state.get("intent") or {}).get("tables") or [])
    return {
        **state,
        "wait_user": False,
        "current_stage": "SCHEMA_PREVIEW",
        "table_schema": {
            "tables": tables,
            "schema_mode": "new_table",
            "schema_preview_text": str(schema_response or "").strip(),
        },
        "output": {
            "type": "schema_preview",
            "message": schema_response,
        },
    }


async def schema_approval(state: AgentState, _llm, _agent) -> AgentState:
    """Pause for human schema review; resume via Command(resume=...)."""
    out = state.get("output") or {}
    ok = interrupt(
        {
            "stage": "SCHEMA_PREVIEW",
            "output": out if isinstance(out, dict) else {},
        }
    )
    if not ok:
        return {
            **state,
            "current_stage": "SCHEMA_APPROVAL",
            "output": {"type": "cancelled", "message": "Schema review cancelled."},
        }
    return {**state, "wait_user": False, "approved": True, "current_stage": "SCHEMA_APPROVAL"}


async def sql_preview(state: AgentState, llm, agent) -> AgentState:
    """Generate CREATE TABLE SQL for user review (no execution yet)."""
    if not state.get("approved"):
        prev = state.get("output") if isinstance(state.get("output"), dict) else {}
        msg = prev.get("message") if isinstance(prev, dict) else None
        return {
            **state,
            "current_stage": "SQL_PREVIEW",
            "sql": None,
            "output": {
                "type": "execution_skipped",
                "sql": None,
                "message": (msg if isinstance(msg, str) and msg.strip() else "Schema review cancelled."),
            },
        }

    if not agent:
        return {
            **state,
            "current_stage": "SQL_PREVIEW",
            "output": {"type": "error", "message": "No agent available"},
            "error": "No agent available",
        }

    from mcp_agent.graph.database_utils import detect_db_type, get_create_table_system_prompt
    db_type = detect_db_type(agent)

    intent = state.get("intent", {})
    effective_message = str(intent.get("resolved_query") or state.get("user_message", ""))
    operation = str(intent.get("operation", "CREATE")).upper()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": get_create_table_system_prompt(db_type)},
    ]
    ts = state.get("table_schema") or {}
    preview_text = str(ts.get("schema_preview_text") or "").strip()
    if preview_text:
        messages.append(
            {
                "role": "system",
                "content": (
                    "User-approved table definition (generate CREATE TABLE SQL that matches this):\n\n"
                    + preview_text
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": f"Operation: {operation}\nTables: {intent.get('tables')}\nRequest: {effective_message}",
        }
    )

    response = llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0,
    )

    from mcp_agent.graph.database_utils import strip_sql_fences
    sql = strip_sql_fences(response.choices[0].message.content or "")

    msg_parts: list[str] = []
    if sql.strip():
        msg_parts.append(f"```sql\n{sql}\n```")
    msg_parts.append("Please review and click Execute")

    return {
        **state,
        "current_stage": "SQL_PREVIEW",
        "sql": sql,
        "output": {
            "type": "sql_preview",
            "sql": sql,
            "message": "\n\n".join(msg_parts).strip(),
        },
    }


async def sql_approval(state: AgentState, _llm, _agent) -> AgentState:
    """Second gate: user must approve the final CREATE TABLE SQL."""
    sql = state.get("sql")
    out = state.get("output") if isinstance(state.get("output"), dict) else {}
    msg = out.get("message") if isinstance(out, dict) else None
    wait_output = {
        "type": "sql_preview",
        "sql": sql,
        "message": (msg if isinstance(msg, str) and msg.strip() else "Please review the SQL and click Execute to run"),
    }
    ok = interrupt({"stage": "SQL_PREVIEW", "output": wait_output})
    if not ok:
        return {
            **state,
            "current_stage": "SQL_PREVIEW",
            "approved": False,
            "output": {**wait_output, "cancelled": True, "message": "SQL execution cancelled."},
        }
    return {**state, "current_stage": "SQL_PREVIEW", "approved": True}


async def sql_execution(state: AgentState, llm, agent) -> AgentState:
    """Execute CREATE TABLE after approval."""
    if not state.get("approved"):
        prev = state.get("output") if isinstance(state.get("output"), dict) else {}
        msg = prev.get("message") if isinstance(prev, dict) else None
        return {
            **state,
            "query_result": None,
            "current_stage": "SQL_EXECUTION",
            "output": {
                "type": "execution_skipped",
                "sql": state.get("sql"),
                "message": (msg if isinstance(msg, str) and msg.strip() else "Schema review cancelled."),
            },
        }

    if not agent:
        return {
            **state,
            "output": {"error": "No agent available for execution"},
            "error": "No agent available"
        }

    from mcp_agent.graph.database_utils import is_execute_query_error_response
    sql = str(state.get("sql") or "").strip()
    if not sql:
        return {
            **state,
            "current_stage": "SQL_EXECUTION",
            "output": {"type": "error", "message": "No SQL available to execute"},
            "error": "No SQL available to execute",
        }

    try:
        response_text = await _call_tool(agent, "execute_query", {"query": sql})
    except Exception as e:
        response_text = f"Error executing SQL: {e}"

    output_type = "error" if is_execute_query_error_response(response_text) else "execution_complete"
    output_message = "Successfully executed the SQL." if output_type == "execution_complete" else response_text

    return {
        **state,
        "sql": sql,
        "query_result": response_text,
        "current_stage": "SQL_EXECUTION",
        "output": {
            "type": output_type,
            "sql": sql,
            "result": response_text,
            "message": output_message,
        }
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


async def _extract_create_table_args(llm, user_message: str) -> dict:
    """Extract create-table tool args from user request as JSON."""
    resp = llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract arguments for show_create_table_schema tool from user request. "
                    "Return strict JSON with keys: table_name (string), columns (string), primary_key (string|null). "
                    "columns must be SQL column list like: 'id SERIAL, name VARCHAR(100), dob DATE'."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    table_name = str(data.get("table_name") or "").strip()
    columns = str(data.get("columns") or "").strip()
    primary_key = data.get("primary_key")
    if primary_key is not None:
        primary_key = str(primary_key).strip() or None

    if not table_name or not columns:
        raise RuntimeError("Could not extract create_table arguments from user request")

    return {
        "table_name": table_name,
        "columns": columns,
        "primary_key": primary_key,
    }


def _generate_create_table_clarification(
    llm,
    user_message: str,
    detected_language: str,
    reason: str = "",
) -> str:
    """Generate user-facing clarification when CREATE TABLE args are incomplete."""
    lang_hint = "Vietnamese" if (detected_language or "").lower() == "vi" else "English"
    try:
        resp = llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly assistant. The user wants to create a data table but did not give enough detail. "
                        "Ask a short, plain-language follow-up: what to name the table, what columns they need, "
                        "and what kind of data each column holds (text, whole number, decimal, date, yes/no). "
                        "Mention they can say which column should be the unique ID if they want one. "
                        "Avoid jargon like VARCHAR or SERIAL; use everyday words. Reply only in the target language."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User message: {user_message}\n"
                        f"Reason: {reason}\n"
                        f"Target language: {lang_hint}\n"
                        "Output only the final user-facing message."
                    ),
                },
            ],
            temperature=0.2,
        )
        out = (resp.choices[0].message.content or "").strip()
        if out:
            return out
    except Exception:
        pass
    if lang_hint == "Vietnamese":
        return (
            "Để tạo bảng giúp bạn, mình cần thêm vài chi tiết đơn giản:\n"
            "• Bạn muốn đặt tên bảng là gì?\n"
            "• Bảng cần những cột nào, mỗi cột lưu loại thông tin gì (ví dụ: chữ, số nguyên, số thập phân, ngày tháng)?\n"
            "• Nếu có một cột dùng làm mã định danh duy nhất cho mỗi dòng (như mã số), hãy cho mình biết tên cột đó."
        )
    return (
        "To set up your table, I need a bit more detail in everyday terms:\n"
        "• What would you like to name the table?\n"
        "• Which columns should it have, and what kind of data goes in each (for example: text, whole numbers, decimals, dates)?\n"
        "• If one column should be a unique ID for each row, tell me which column that should be."
    )


class CreateTableWorkflow:
    """Create table workflow with schema preview and human approval.

    Nodes:
    1. INTENT_PARSE - classify operation (expects CREATE)
    2. SCHEMA_PREVIEW - show CREATE TABLE schema
    3. SCHEMA_APPROVAL - interrupt for human review
    4. SQL_PREVIEW - generate final CREATE TABLE SQL
    5. SQL_APPROVAL - interrupt for human approval of SQL
    6. SQL_EXECUTION - execute after approval

    Flow: START → INTENT_PARSE → SCHEMA_PREVIEW → SCHEMA_APPROVAL → SQL_PREVIEW → SQL_APPROVAL → SQL_EXECUTION → DONE
    """

    def __init__(self, llm=None, agent=None):
        self.llm = llm or OpenAI()
        self.agent = agent
        self._compiled_graph = None

    def _build_graph(self, checkpointer):
        """Build LangGraph for create table workflow."""
        workflow = StateGraph(AgentState)

        async def intent_parse_node(state):
            return await intent_parse(state, self.llm, self.agent)

        async def schema_preview_node(state):
            return await schema_preview(state, self.llm, self.agent)

        async def schema_approval_node(state):
            return await schema_approval(state, self.llm, self.agent)

        async def sql_preview_node(state):
            return await sql_preview(state, self.llm, self.agent)

        async def sql_approval_node(state):
            return await sql_approval(state, self.llm, self.agent)

        async def sql_execution_node(state):
            return await sql_execution(state, self.llm, self.agent)

        async def done_handler(state):
            return {**state, "current_stage": StageType.DONE.value}

        workflow.add_node("INTENT_PARSE", intent_parse_node)
        workflow.add_node("SCHEMA_PREVIEW", schema_preview_node)
        workflow.add_node("SCHEMA_APPROVAL", schema_approval_node)
        workflow.add_node("SQL_PREVIEW", sql_preview_node)
        workflow.add_node("SQL_APPROVAL", sql_approval_node)
        workflow.add_node("SQL_EXECUTION", sql_execution_node)
        workflow.add_node(StageType.DONE.value, done_handler)

        workflow.set_entry_point("INTENT_PARSE")
        workflow.add_edge("INTENT_PARSE", "SCHEMA_PREVIEW")
        workflow.add_edge("SCHEMA_PREVIEW", "SCHEMA_APPROVAL")
        workflow.add_edge("SCHEMA_APPROVAL", "SQL_PREVIEW")
        workflow.add_edge("SQL_PREVIEW", "SQL_APPROVAL")
        workflow.add_edge("SQL_APPROVAL", "SQL_EXECUTION")
        workflow.add_edge("SQL_EXECUTION", StageType.DONE.value)
        workflow.add_edge(StageType.DONE.value, END)

        return workflow.compile(checkpointer=checkpointer)

    async def _get_compiled_graph(self):
        if self._compiled_graph is None:
            checkpointer = await get_async_checkpointer()
            self._compiled_graph = self._build_graph(checkpointer)
        return self._compiled_graph

    async def run(
        self,
        session_id: str,
        user_message: str,
        *,
        resume=None,
        thread_id: str = None,
    ) -> AgentState:
        """Run or resume the create table workflow."""
        graph = await self._get_compiled_graph()
        # Keep thread-only config, but isolate checkpoint stream per workflow
        # to avoid collision with chat graph / other workflows sharing session_id.
        wf_thread_id = f"{thread_id or session_id}:create_table"
        cfg = {
            "configurable": {
                "thread_id": wf_thread_id,
            }
        }
        if resume is not None:
            raw = await graph.ainvoke(Command(resume=resume), cfg, version=GRAPH_INVOKE_VERSION)
            logger.info("[CreateTable] Resume invoke raw type=%s", type(raw).__name__)
            # ainvoke(Command(resume=)) returns a GraphOutput delta (e.g. {'intent': ...}),
            # not the full accumulated state.  Use the same hydration path as the initial invoke:
            # normalise what we can from the delta, then hydrate the rest from the checkpoint history.
            normalized = _normalize_graph_result(raw)
            hydrated = await _hydrate_from_checkpoint(graph, cfg, normalized)
            # Additionally expose any pending interrupt from the snapshot (sql_approval gate).
            try:
                snap = await graph.aget_state(cfg)
                tasks = getattr(snap, "tasks", None) if snap else None
                if isinstance(tasks, list):
                    for t in tasks:
                        interrupts = getattr(t, "interrupts", None)
                        if interrupts:
                            hydrated["__interrupt__"] = interrupts
                            break
            except Exception:
                pass
        else:
            state = create_initial_state(session_id, user_message, "database")
            raw = await graph.ainvoke(state, cfg, version=GRAPH_INVOKE_VERSION)
            logger.info("[CreateTable] Initial invoke raw type=%s", type(raw).__name__)
            normalized = _normalize_graph_result(raw)
            hydrated = await _hydrate_from_checkpoint(graph, cfg, normalized)
        logger.info(
            "[CreateTable] Result keys=%s, stage=%s, output_type=%s, pending_gate=%s",
            list(hydrated.keys()),
            hydrated.get("current_stage"),
            ((hydrated.get("output") or {}).get("type") if isinstance(hydrated.get("output"), dict) else None),
            str(hydrated.get("current_stage") or "") in ("SCHEMA_PREVIEW", "SQL_PREVIEW"),
        )
        return hydrated