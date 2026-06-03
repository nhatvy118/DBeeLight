"""Mutation workflow - INSERT/UPDATE/DELETE with SQL preview and human approval."""

import json
import logging
import re
from typing import Dict

from openai import OpenAI
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from mcp_agent.graph.database_utils import (
    alter_sql_to_select_preview,
    build_mutation_schema_context_block,
    build_sql_preview_message,
    delete_sql_to_select_preview,
    detect_db_type,
    drop_sql_to_select_preview,
    format_mutation_preview_markdown,
    get_sql_system_prompt,
    insert_into_select_preview_sql,
    insert_values_preview_markdown,
    is_execute_query_error_response,
    markdown_table_from_rows,
    parse_describe_table_column_names,
    parse_table_names_from_list_tools,
    sql_generation_failure_message,
    strip_sql_fences,
    update_sql_to_select_preview,
    validate_explain_and_summarize,
)
from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.langgraph_checkpointer import get_async_checkpointer
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
            logger.info("[Mutation] aget_state with checkpoint_ns failed, retry thread-only")
            snapshot = await graph.aget_state(fallback_cfg)
        else:
            raise
    hydrated: AgentState = {}
    values = getattr(snapshot, "values", None) if snapshot else None
    if isinstance(values, dict) and values:
        hydrated = dict(values)

    tasks = getattr(snapshot, "tasks", None) if snapshot else None
    if isinstance(tasks, list):
        for t in tasks:
            interrupts = getattr(t, "interrupts", None)
            if interrupts:
                hydrated["__interrupt__"] = interrupts
                break
    return hydrated


async def intent_parse(state: AgentState, llm, agent) -> AgentState:
    """Parse user intent and determine mutation operation."""
    # Handle resume: user_message may not be in checkpoint state
    intent_data = state.get("intent") or {}
    user_message = state.get("user_message") or str(intent_data.get("resolved_query") or "")
    logger.info(f"[Mutation] Intent parse: {user_message[:50]}...")
    recent_context = await _get_recent_session_context(agent)

    orch_intent = state.get("orchestrator_intent") if isinstance(state.get("orchestrator_intent"), dict) else {}
    orch_nl = str((orch_intent or {}).get("nl_query") or "").strip()
    orch_table_hint = str((orch_intent or {}).get("table_hint") or "").strip()

    orch_block = ""
    if orch_nl or orch_table_hint:
        orch_block = (
            "Orchestrator (authoritative hints from top-level router):\n"
            f"- nl_query: {orch_nl or '(none)'}\n"
            f"- table_hint: {orch_table_hint or '(none)'}\n"
        )

    response = llm.chat.completions.create(
        model="gpt-5.2",
        messages=[
            {
                "role": "system",
                "content": """Analyze the database request and extract:
- operation: SELECT, INSERT, UPDATE, DELETE, ALTER, DROP, etc.
- tables: list of every table name referenced (required for mutations).
  If the user says "this table" and orchestrator table_hint is set, use that table name.
  If nl_query names a table (e.g. schedule), include it in tables.
- filters: WHERE conditions
- resolved_query: rewrite latest user message into a self-contained request

Return JSON."""
            },
            {
                "role": "user",
                "content": (
                    f"Latest user message: {user_message}\n\n"
                    f"{orch_block}\n"
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

    operation = str(intent.get("operation", "INSERT")).strip().upper()
    resolved_query = (
        str(intent.get("resolved_query") or "").strip()
        or orch_nl
        or user_message
    )

    merged_tables: list = list(intent.get("tables") or [])
    raw_um = str(state.get("user_message") or "")
    if "AVAILABLE SQLITE TABLES" in raw_um:
        for t in re.findall(r"table:\s*`([^`]+)`", raw_um):
            if t and t not in merged_tables:
                merged_tables.append(t)

    if orch_table_hint:
        forced = [t.strip() for t in orch_table_hint.split(",") if t.strip()]
        if forced:
            merged_tables = forced
            logger.info("[Mutation] orchestrator table_hint overrides tables → %s", merged_tables)

    safe_intent = {
        "operation": operation,
        "tables": merged_tables,
        "filters": intent.get("filters", {}),
        "resolved_query": resolved_query,
    }

    logger.info(
        "[Mutation] Parsed operation=%s, tables=%s",
        operation,
        safe_intent.get("tables"),
    )

    return {
        **state,
        "intent": safe_intent,
        "followup_context": recent_context,
    }


async def schema_discovery(state: AgentState, llm, agent) -> AgentState:
    """Load schema context by operation: existing rows, ALTER (existing + new cols), or CREATE (new table)."""
    intent = state.get("intent") or {}
    operation = str(intent.get("operation", "INSERT")).strip().upper()
    tables = list(intent.get("tables") or [])
    logger.info(f"[Mutation] Schema discovery for: {tables} (operation={operation})")

    if not agent:
        return {**state, "table_schema": {}}

    log_lines: list[str] = []
    tables_result = ""
    try:
        tables_result = await _call_tool(agent, "list_tables", {})
        log_lines.append(f"list_tables: {tables_result}")
    except Exception as e:
        log_lines.append(f"list_tables error: {e}")

    all_tables = parse_table_names_from_list_tools(tables_result)
    all_lower = {t.lower() for t in all_tables}
    tables_work = [str(t).strip() for t in tables if str(t).strip()]

    # CREATE TABLE via mutation (prefer db_create_table workflow): table must not exist yet.
    if operation == "CREATE":
        already = [t for t in tables_work if t.lower() in all_lower]
        if already:
            names = ", ".join(f"`{t}`" for t in already)
            msg = (
                f"**Table already exists:** {names}\n\n"
                "Use INSERT/UPDATE on this table, or pick a new name for CREATE TABLE.\n\n"
                f"**Existing tables:** {', '.join(f'`{t}`' for t in all_tables[:40])}"
            )
            return {
                **state,
                "schema_discovery_failed": True,
                "error": f"Table(s) already exist: {', '.join(already)}",
                "output": {"type": "error", "message": msg},
                "table_schema": {
                    "tables": tables_work,
                    "all_tables": list(all_tables),
                    "descriptions": {},
                    "schema_mode": "new_table",
                },
            }
        log_block = "\n".join(log_lines)
        logger.info("[Mutation] CREATE — skip describe_table (new table)")
        return {
            **state,
            "intent": {**intent, "tables": tables_work},
            "table_schema": {
                "tables": tables_work,
                "all_tables": list(all_tables),
                "descriptions": {},
                "schema_mode": "new_table",
            },
        }

    missing: list[str] = []
    descriptions: dict[str, str] = {}
    schema_mode = "alter_table" if operation == "ALTER" else "existing_table"

    for name in list(dict.fromkeys(tables_work)):
        try:
            d = await _call_tool(agent, "describe_table", {"table_name": name})
            log_lines.append(f"describe_table({name}): {d}")
            if _describe_table_succeeded(d):
                descriptions[name] = str(d).strip()
            elif name in tables_work:
                missing.append(name)
        except Exception as e:
            log_lines.append(f"describe_table({name}) error: {e}")
            if name in tables_work:
                missing.append(name)

    log_block = "\n".join(log_lines)
    logger.info(f"[Mutation] Schema discovery response: {log_block[:500]}...")

    table_schema = {
        "tables": tables_work,
        "all_tables": list(all_tables),
        "descriptions": descriptions,
        "schema_mode": schema_mode,
    }

    if missing:
        miss_fmt = ", ".join(f"{m}" for m in missing)
        available = ", ".join(f"`{t}`" for t in all_tables[:40]) if all_tables else "(none)"
        msg = (
            f"**Unknown table(s):** {miss_fmt}\n\n"
            "Those tables are not in the connected database. "
            "Fix the table name or create the table before continuing.\n\n"
            f"**Available tables:** {available}\n\n"
            "**Discovery log:**\n\n\n"
            f"{log_block[:8000]}\n\n"
        )
        return {
            **state,
            "schema_discovery_failed": True,
            "error": f"Table(s) not found: {', '.join(missing)}",
            "output": {
                "type": "error",
                "message": msg,
            },
            "table_schema": {**table_schema, "missing": missing},
        }

    intent_patch = {**(state.get("intent") or {}), "tables": tables_work}
    return {
        **state,
        "intent": intent_patch,
        "table_schema": table_schema,
    }


async def sql_preview(state: AgentState, llm, agent) -> AgentState:
    """Generate SQL and show preview with affected rows."""
    intent = state.get("intent", {})
    effective_message = str(intent.get("resolved_query") or state.get("user_message", ""))
    operation = intent.get("operation", "INSERT").upper()
    logger.info(f"[Mutation] SQL preview for: {operation}")

    if not agent:
        return {
            **state,
            "output": {"type": "error", "message": "No agent available"},
        }

    db_type = detect_db_type(agent)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": get_sql_system_prompt(db_type, operation=operation)},
    ]
    schema_block = build_mutation_schema_context_block(
        state.get("table_schema") or {},
        operation=operation,
    )
    if schema_block:
        messages.append({"role": "system", "content": schema_block})
        logger.info("[Mutation] SQL generation schema context (%d chars)", len(schema_block))
    messages.append(
        {
            "role": "user",
            "content": (
                f"Operation: {operation}\n"
                f"Target tables: {intent.get('tables')}\n"
                f"Filters: {intent.get('filters')}\n"
                f"Request: {effective_message}"
            ),
        }
    )

    max_attempts = 3
    sql = ""
    last_error = ""
    final_out: Dict | None = None

    retry_messages = list(messages)
    for attempt in range(1, max_attempts + 1):
        response = llm.chat.completions.create(
            model="gpt-5.2",
            messages=retry_messages,
            temperature=0,
        )
        sql = strip_sql_fences(response.choices[0].message.content or "")

        ok, explain_err, explain_summary, type_sql = await validate_explain_and_summarize(
            agent,
            llm,
            _call_tool,
            sql=sql,
            operation=operation,
            request=effective_message,
            db_type=db_type,
        )
        if not ok:
            last_error = explain_err
            if attempt < max_attempts:
                retry_messages.extend(
                    [
                        {"role": "assistant", "content": sql},
                        {
                            "role": "system",
                            "content": (
                                "The previous SQL failed validation or EXPLAIN. "
                                "Generate a corrected SQL statement only.\n"
                                f"Error: {explain_err}"
                            ),
                        },
                    ]
                )
                continue
            break

        out: Dict = {
            "type": "sql_preview",
            "sql": sql,
            "message": "Please review and click Execute",
        }
        if explain_summary:
            out["explain_summary"] = explain_summary
        if type_sql:
            out["type_sql"] = type_sql
        out = await _enrich_mutation_preview(agent, operation, sql, out)
        if out.get("mutation_preview_fatal"):
            last_error = str(out.get("mutation_preview_error_raw") or "Preview failed")
            if attempt < max_attempts:
                retry_messages.extend(
                    [
                        {"role": "assistant", "content": sql},
                        {
                            "role": "system",
                            "content": (
                                "The previous SQL failed when running preview. "
                                "Generate a corrected SQL statement only.\n"
                                f"Preview error: {last_error}"
                            ),
                        },
                    ]
                )
                continue
            break

        final_out = out
        break

    if final_out is None:
        msg = sql_generation_failure_message(last_error)
        if "preview" in (last_error or "").lower():
            msg = (
                f"{msg}\n\n"
                f"Last preview error:\n{last_error}"
            )
        return {
            **state,
            "sql": None,
            "wait_user": False,
            "error": "SQL generation/validation failed",
            "output": {"type": "error", "message": msg},
        }

    out = final_out

    # SQL + EXPLAIN summary + row preview for frontend Execute affordance.
    preview_md = out.get("mutation_preview_markdown")
    out["message"] = build_sql_preview_message(
        sql,
        explain_summary=out.get("explain_summary"),
        preview_md=preview_md if isinstance(preview_md, str) else None,
    )

    return {
        **state,
        "sql": sql,
        "error": None,
        "schema_discovery_failed": False,
        "current_stage": "SQL_PREVIEW",
        "wait_user": False,
        "output": out,
    }


async def _enrich_mutation_preview(agent, operation: str, sql: str, out: Dict) -> Dict:
    """Attach row preview: VALUES table for INSERT, derived SELECT for UPDATE/DELETE, etc."""
    out = dict(out)
    op = str(operation).upper()
    if not agent:
        return out

    if op == "DELETE":
        preview_q = delete_sql_to_select_preview(sql)
        return await _mutation_preview_run_select(
            agent, out, "Rows that would be deleted (preview)", preview_q
        )

    if op == "UPDATE":
        preview_q = update_sql_to_select_preview(sql)
        if preview_q:
            return await _mutation_preview_run_select(
                agent, out, "Rows that would be updated (current values, preview)", preview_q
            )
        return {
            **out,
            "mutation_preview_markdown": (
                "**Rows that would be updated (preview)**\n\n"
                "_Could not derive a safe SELECT from this UPDATE. Review the SQL above._"
            ),
        }

    if op == "INSERT":
        # INSERT ... VALUES → markdown table of tuples (what will be inserted).
        if re.search(r"\bVALUES\b", sql, re.IGNORECASE):
            out["mutation_preview_markdown"] = await insert_values_preview_markdown(
                agent, sql, _call_tool
            )
            return out
        # INSERT ... SELECT → run subquery read-only; label so UI is not confused with a lone SELECT.
        sel = insert_into_select_preview_sql(sql)
        if sel:
            out = await _mutation_preview_run_select(
                agent,
                out,
                "Source rows for INSERT … SELECT (read-only preview)",
                sel,
            )
            mp = out.get("mutation_preview_markdown")
            if isinstance(mp, str) and mp.strip():
                out["mutation_preview_markdown"] = (
                    "_Full statement is `INSERT … SELECT` in the SQL block above. "
                    "The table below previews only the **SELECT** subquery (not executed as INSERT yet)._\n\n"
                    + mp.strip()
                )
            return out
        out["mutation_preview_markdown"] = await insert_values_preview_markdown(agent, sql, _call_tool)
        return out

    if op == "DROP":
        preview_q = drop_sql_to_select_preview(sql)
        if preview_q:
            return await _mutation_preview_run_select(
                agent, out, "Current rows in object to be dropped (preview)", preview_q
            )
        return {
            **out,
            "mutation_preview_markdown": (
                "**DROP (preview)**\n\n"
                "_Could not derive a row preview (expect `DROP TABLE` / `DROP VIEW` on one object)._"
            ),
        }

    if op == "ALTER":
        preview_q = alter_sql_to_select_preview(sql)
        if preview_q:
            return await _mutation_preview_run_select(
                agent, out, "Current rows in table before ALTER (preview)", preview_q
            )
        return {
            **out,
            "mutation_preview_markdown": (
                "**ALTER (preview)**\n\n"
                "_Could not derive table name for row preview. Review the SQL above._"
            ),
        }

    return out


async def _mutation_preview_run_select(
    agent, out: Dict, title: str, select_sql: str
) -> Dict:
    """Execute read-only SELECT and attach formatted rows."""
    out = dict(out)
    if not agent or not select_sql:
        return out
    try:
        logger.info("[Mutation] Preview SELECT: %s", select_sql[:300])
        preview_raw = await _call_tool(agent, "execute_query", {"query": select_sql})
        if is_execute_query_error_response(preview_raw):
            logger.warning("[Mutation] Preview SELECT failed: %s", (preview_raw or "")[:300])
            out["mutation_preview_fatal"] = True
            out["mutation_preview_error_raw"] = preview_raw
            return out

        # If the DB tool returns a plain "no rows" string, render an empty table with headers
        # so the UI shows columns even when 0 rows match.
        low = (preview_raw or "").strip().lower()
        if "no rows returned" in low or "no data found" in low:
            table_name = None
            try:
                m = re.search(r"\bfrom\s+([a-zA-Z0-9_\"`\.]+)", select_sql, flags=re.IGNORECASE)
                if m:
                    table_name = m.group(1).strip().strip("`").strip('"')
            except Exception:
                table_name = None
            headers: list[str] = []
            if table_name:
                try:
                    desc = await _call_tool(agent, "describe_table", {"table_name": table_name})
                    headers = parse_describe_table_column_names(desc) or []
                except Exception:
                    headers = []
            if headers:
                empty_table = markdown_table_from_rows(headers, [])
                out["mutation_preview_markdown"] = f"**{title}**\n\n{empty_table}\n\n_No matching rows._"
            else:
                out["mutation_preview_markdown"] = format_mutation_preview_markdown(title, preview_raw)
        else:
            out["mutation_preview_markdown"] = format_mutation_preview_markdown(title, preview_raw)
    except Exception as e:
        logger.warning("[Mutation] mutation preview SELECT failed (%s): %s", title, e)
        out["mutation_preview_fatal"] = True
        out["mutation_preview_error_raw"] = str(e)
    return out


async def sql_approval(state: AgentState, _llm, _agent) -> AgentState:
    """Human approval for executing generated SQL (LangGraph interrupt)."""
    sql = state.get("sql")
    prev_out = state.get("output") if isinstance(state.get("output"), dict) else {}
    wait_output: Dict = {
        "type": "sql_preview",
        "sql": sql,
        "message": "Please review the SQL and click Execute to run",
    }
    mp = prev_out.get("mutation_preview_markdown")
    if isinstance(mp, str) and mp.strip():
        wait_output["mutation_preview_markdown"] = mp.strip()
    es = prev_out.get("explain_summary")
    if isinstance(es, str) and es.strip():
        wait_output["explain_summary"] = es.strip()
    wait_output["message"] = build_sql_preview_message(
        sql or "",
        explain_summary=es if isinstance(es, str) else None,
        preview_md=mp if isinstance(mp, str) else None,
        footer="Please review the SQL and click Execute to run",
    )

    logger.info("[Mutation] SQL approval interrupt")
    ok = interrupt(
        {
            "stage": "SQL_PREVIEW",
            "output": wait_output,
        }
    )
    if not ok:
        return {
            **state,
            "approved": False,
            "wait_user": False,
            "output": {
                **wait_output,
                "cancelled": True,
                "message": "SQL execution cancelled.",
            },
        }
    return {
        **state,
        "approved": True,
        "current_stage": "SQL_PREVIEW",
        "wait_user": False,
    }


async def sql_execution(state: AgentState, llm, agent) -> AgentState:
    """Execute SQL query after approval."""
    sql = state.get("sql")
    logger.info(f"[Mutation] SQL execution: {sql[:50] if sql else 'None'}...")

    if not state.get("approved"):
        prev = state.get("output") if isinstance(state.get("output"), dict) else {}
        msg = prev.get("message") if isinstance(prev, dict) else None
        return {
            **state,
            "query_result": None,
            "output": {
                "type": "execution_skipped",
                "sql": sql,
                "message": (msg if isinstance(msg, str) and msg.strip() else "SQL execution cancelled."),
            },
        }

    if not agent:
        return {
            **state,
            "output": {"error": "No agent available for execution"},
            "error": "No agent available"
        }

    try:
        response = await _call_tool(agent, "execute_query", {"query": sql})
    except Exception as e:
        response = f"Error executing SQL: {e}"

    is_err = is_execute_query_error_response(str(response))
    if is_err:
        message = str(response).strip()
    else:
        message = "Successfully executed the SQL."
    output_type = "error" if is_err else "execution_complete"

    return {
        **state,
        "query_result": response,
        "output": {
            "type": output_type,
            "sql": sql,
            "result": response,
            "message": message,
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


class MutationWorkflow:
    """Mutation workflow for INSERT/UPDATE/DELETE with SQL preview and approval.

    Nodes:
    1. INTENT_PARSE - classify operation
    2. SCHEMA_DISCOVERY - verify tables exist
    3. SQL_PREVIEW - generate SQL with affected rows preview
    4. SQL_APPROVAL - interrupt for human approval
    5. SQL_EXECUTION - execute after approval

    Flow: START → INTENT_PARSE → SCHEMA_DISCOVERY → SQL_PREVIEW → SQL_APPROVAL → SQL_EXECUTION → DONE
    """

    def __init__(self, llm=None, agent=None):
        self.llm = llm or OpenAI()
        self.agent = agent
        self._compiled_graph = None

    def _build_graph(self, checkpointer):
        """Build LangGraph for mutation workflow."""
        workflow = StateGraph(AgentState)

        async def intent_parse_node(state):
            return await intent_parse(state, self.llm, self.agent)

        async def schema_discovery_node(state):
            return await schema_discovery(state, self.llm, self.agent)

        async def sql_preview_node(state):
            return await sql_preview(state, self.llm, self.agent)

        async def sql_approval_node(state):
            return await sql_approval(state, self.llm, self.agent)

        async def sql_execution_node(state):
            return await sql_execution(state, self.llm, self.agent)

        async def done_handler(state):
            return {**state, "current_stage": StageType.DONE.value}

        def route_after_schema(state):
            """Stop before SQL generation when schema discovery failed."""
            out = state.get("output") or {}
            if state.get("schema_discovery_failed") or out.get("type") == "error":
                return StageType.DONE.value
            return "SQL_PREVIEW"

        def route_after_preview(state):
            """Skip approval only when sql_preview returned an error output."""
            if (state.get("output") or {}).get("type") == "error":
                return StageType.DONE.value
            return "SQL_APPROVAL"

        workflow.add_node("INTENT_PARSE", intent_parse_node)
        workflow.add_node("SCHEMA_DISCOVERY", schema_discovery_node)
        workflow.add_node("SQL_PREVIEW", sql_preview_node)
        workflow.add_node("SQL_APPROVAL", sql_approval_node)
        workflow.add_node("SQL_EXECUTION", sql_execution_node)
        workflow.add_node(StageType.DONE.value, done_handler)

        workflow.set_entry_point("INTENT_PARSE")
        workflow.add_edge("INTENT_PARSE", "SCHEMA_DISCOVERY")
        workflow.add_conditional_edges(
            "SCHEMA_DISCOVERY",
            route_after_schema,
            {"SQL_PREVIEW": "SQL_PREVIEW", StageType.DONE.value: StageType.DONE.value},
        )
        workflow.add_conditional_edges(
            "SQL_PREVIEW",
            route_after_preview,
            {"SQL_APPROVAL": "SQL_APPROVAL", StageType.DONE.value: StageType.DONE.value},
        )
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
        orchestrator_intent: Dict | None = None,
    ) -> AgentState:
        """Run or resume the mutation workflow."""
        graph = await self._get_compiled_graph()
        # Keep thread-only config, but isolate checkpoint stream per workflow
        # to avoid collision with chat graph / other workflows sharing session_id.
        wf_thread_id = f"{thread_id or session_id}:mutation"
        cfg = {
            "configurable": {
                "thread_id": wf_thread_id,
            }
        }
        if resume is not None:
            raw = await graph.ainvoke(Command(resume=resume), cfg, version=GRAPH_INVOKE_VERSION)
            normalized = _normalize_graph_result(raw)
            hydrated = await _hydrate_from_checkpoint(graph, cfg, normalized)
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
            if orchestrator_intent:
                state = {**state, "orchestrator_intent": orchestrator_intent}
            raw = await graph.ainvoke(state, cfg, version=GRAPH_INVOKE_VERSION)
            normalized = _normalize_graph_result(raw)
            hydrated = await _hydrate_from_checkpoint(graph, cfg, normalized)
        return hydrated
