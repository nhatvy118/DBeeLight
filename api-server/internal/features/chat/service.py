from __future__ import annotations

import asyncio
import importlib
import json as _json
import logging
import os
import re
import time
import uuid
from typing import AsyncIterator, Optional

from fastapi import HTTPException

from internal.features.chat.repository import AgentRepository
from internal.features.file.service import FileService
from internal.features.project.repository import ProjectRepository
from internal.features.share.repository import ChatShareRepository

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

logger = logging.getLogger(__name__)

_chat_graph = importlib.import_module("mcp_agent.graph.chat_graph")
chat_checkpoint_config = _chat_graph.chat_checkpoint_config
_progress = importlib.import_module("mcp_agent.progress")
set_progress_callback = _progress.set_progress_callback
reset_progress_callback = _progress.reset_progress_callback
progress_emit = _progress.emit


def _sse_format(event: dict) -> str:
    """Format an event dict as a Server-Sent Events frame.

    Spec: each frame is one or more ``key: value`` lines terminated by a blank
    line. We use the optional ``event:`` line so clients can dispatch on type.
    """
    event_type = str(event.get("type") or "message")
    data = _json.dumps(event, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"


_READ_ONLY_SQL_VERBS = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "PRAGMA"}


def _looks_like_summary_request(text: str) -> bool:
    q = (text or "").strip().lower()
    if not q:
        return False
    # English
    if any(w in q for w in ("summarize", "summary", "summarise", "tl;dr")):
        return True
    return False

# Permission ladder: view_only < read_data < edit_data. A request is allowed

_READ_DATA_SYSTEM_NOTE = (
    "[SHARED SESSION — READ-ONLY MODE] This session was shared with you in "
    "read-only mode. You may run SELECT/WITH/SHOW/DESCRIBE/EXPLAIN queries to "
    "explore the data, but you must NOT propose or execute INSERT/UPDATE/DELETE/"
    "ALTER/DROP/CREATE/TRUNCATE statements, or any operation that changes data "
    "or schema. If the user asks for a write operation, refuse and explain the "
    "restriction."
)


def _is_read_only_sql(sql: str) -> bool:
    """Return True if the SQL's first verb is read-only."""
    s = (sql or "").strip().lstrip("(").lstrip()
    if not s:
        return False
    first = s.split()[:1]
    if not first:
        return False
    return first[0].upper() in _READ_ONLY_SQL_VERBS


def _classify_file_data_intent_heuristic(text: str) -> str:
    """Return `yes` | `no` | `uncertain` for file-data intent."""
    s = (text or "").strip().lower()
    if not s:
        return "no"

    strong_yes = (
        "from file",
        "from uploaded file",
        "uploaded file",
        "in file",
        "in excel",
        "in sheet",
        "trong file",
        "trong excel",
        "trong sheet",
        "where ",
        "group by",
        "having",
        "order by",
        "count(",
        "sum(",
        "avg(",
        "min(",
        "max(",
    )
    if any(p in s for p in strong_yes):
        return "yes"

    likely_yes = (
        "filter",
        "column",
        "sheet",
        "row",
        "dob",
        " > ",
        " < ",
        " = ",
        ">=",
        "<=",
    )
    if any(p in s for p in likely_yes):
        return "uncertain"

    strong_no = (
        "hello",
        "hi ",
        "thanks",
        "thank you",
        "explain architecture",
        "debug",
        "fix bug",
        "deploy",
        "help me",
    )
    if any(p in s for p in strong_no):
        return "no"

    return "uncertain"


class ChatService:
    def __init__(
        self,
        agent_repo: AgentRepository,
        project_repo: Optional[ProjectRepository] = None,
        share_repo: Optional[ChatShareRepository] = None,
        file_service: Optional[FileService] = None,
    ):
        self._agent_repo = agent_repo
        self._project_repo = project_repo
        self._share_repo = share_repo
        self._file_usecase = file_service

    async def _get_share_context(
        self, session_id: str | None, user_key: str
    ) -> dict | None:
        """Return share context for a forked session, or None if not forked.

        Returned dict has keys: ``permission`` (str), ``owner_user_id`` (str —
        google_sub of the original owner; used to look up the project's db_url
        which is scoped to that owner).

        Raises HTTPException(403) if the session is forked but revoked, or if the
        caller is not the intended recipient.
        """
        if not (session_id or "").strip():
            return None
        if self._share_repo is None:
            return None
        info = await self._share_repo.get_share_permission_for_session(session_id)
        if info is None:
            return None
        if info["revoked"]:
            raise HTTPException(status_code=403, detail="This shared session has been revoked")
        rec_sub = info.get("recipient_user_id")
        if rec_sub and rec_sub != user_key:
            raise HTTPException(
                status_code=403,
                detail="This shared session belongs to another user",
            )
        return {
            "permission": str(info["permission"]),
            "owner_user_id": str(info["owner_user_id"]),
            # Project the share was created against (owned by owner_user_id).
            # Frontend may not have it in its local project list (only the owner
            # does), so we fall back to this when callers omit project_id.
            "project_id": str(info["project_id"]) if info.get("project_id") else None,
        }

    @staticmethod
    def _extract_last_mutation_sql_block(text: str) -> str | None:
        matches = re.findall(r"```\s*sql\s*([\s\S]*?)```", text or "", flags=re.IGNORECASE)
        if not matches:
            return None
        last = (matches[-1] or "").strip()
        if not last:
            return None
        first_token = (last.split()[:1] or [""])[0].upper()
        if first_token in {"SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH", "PRAGMA"}:
            return None
        return last

    @staticmethod
    def _attach_sql_action_id_marker(text: str, action_id: str) -> str:
        return f"{text}\n\n[SQL_ACTION_ID_START]{action_id}[SQL_ACTION_ID_END]"

    async def _maybe_persist_excel_export_in_assistant_reply(
        self, response_text: str, session_id: str | None, user_key: str
    ) -> str:
        """Persist inline Excel export to ``file_handle/{{user}}/{{session}}/export/`` and strip base64."""
        if (
            not self._file_usecase
            or not (session_id or "").strip()
            or user_key == "anonymous"
            or "[EXCEL_BASE64_START]" not in (response_text or "")
        ):
            return response_text
        try:
            return await self._file_usecase.rewrite_assistant_text_persist_excel_export(
                response_text,
                session_id=(session_id or "").strip(),
                user_key=user_key,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(
                "Persist Excel export failed (keeping inline base64): %s",
                e,
                exc_info=True,
            )
            return response_text

    @staticmethod
    def _extract_sql_preview_from_tool_events(tool_events: list[dict]) -> str | None:
        """Prefer structured sql_preview tool event over parsing assistant text."""
        if not isinstance(tool_events, list):
            return None
        for e in tool_events:
            if not isinstance(e, dict):
                continue
            if str(e.get("type") or "") != "sql_preview":
                continue
            payload = e.get("payload")
            if not isinstance(payload, dict):
                continue
            sql = payload.get("sql")
            if isinstance(sql, str) and sql.strip():
                return sql.strip()
        return None

    async def _llm_file_data_intent_check(self, query: str) -> tuple[bool | None, float]:
        """
        Ask LLM whether the query likely needs uploaded-file data.
        Returns (decision_or_none, latency_ms).
        """
        t0 = time.perf_counter()
        try:
            from openai import AsyncOpenAI
        except Exception:
            return None, (time.perf_counter() - t0) * 1000.0

        client = AsyncOpenAI()
        model = os.getenv("FILE_INTENT_MODEL", "gpt-5.2")
        timeout_s = max(0.5, float(os.getenv("FILE_INTENT_TIMEOUT_S", "3.0")))
        prompt = (
            "Decide if the user message needs data from an uploaded file in this chat session. "
            "Return JSON only: {\"use_file_data\": true|false}. "
            "True for filters/aggregations/column lookups over uploaded spreadsheets. "
            "False for generic conversation, architecture, debugging, or unrelated DB questions."
        )
        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=20,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": query[:2000]},
                    ],
                    response_format={"type": "json_object"},
                ),
                timeout=timeout_s,
            )
            content = (resp.choices[0].message.content or "").strip()
            parsed = _json.loads(content) if content else {}
            v = parsed.get("use_file_data")
            if isinstance(v, bool):
                return v, (time.perf_counter() - t0) * 1000.0
            return None, (time.perf_counter() - t0) * 1000.0
        except Exception:
            return None, (time.perf_counter() - t0) * 1000.0

    async def _resolve_file_data_intent(
        self,
        query: str,
        *,
        should_try_llm: bool,
    ) -> tuple[bool, str, str, float | None]:
        """
        Resolve file-data intent using heuristic + optional LLM.
        Returns: (decision, decision_source, heuristic_state, llm_latency_ms_or_none)
        """
        heuristic_state = _classify_file_data_intent_heuristic(query)
        if heuristic_state == "yes":
            return True, "heuristic", heuristic_state, None
        if heuristic_state == "no":
            return False, "heuristic", heuristic_state, None
        if not should_try_llm:
            return False, "heuristic_uncertain_default", heuristic_state, None

        llm_decision, llm_latency_ms = await self._llm_file_data_intent_check(query)
        if llm_decision is None:
            # Fallback policy requested: heuristic-only on LLM failure.
            return False, "fallback_heuristic", heuristic_state, llm_latency_ms
        return bool(llm_decision), "llm", heuristic_state, llm_latency_ms

    async def _persist_pending_approval_from_workflow(
        self,
        agent,
        session_id: str | None,
        *,
        pending_workflow_resume: bool,
        workflow_state: dict | None,
        tool_events: list[dict],
    ) -> None:
        """Persist pending approval so /api/sql/execute can validate SQL gate."""
        if not pending_workflow_resume:
            return
        if not (session_id or "").strip():
            return
        if not getattr(agent, "session_manager", None):
            return
        ws = workflow_state if isinstance(workflow_state, dict) else {}
        stage = str(ws.get("current_stage") or "")
        if stage not in {"SQL_PREVIEW", "SCHEMA_PREVIEW"}:
            # We only care about these two gates for now.
            return
        sql = self._extract_sql_preview_from_tool_events(tool_events)
        payload = {
            "kind": "workflow_langgraph_interrupt",
            "interrupt_stage": stage,
        }
        if sql:
            payload["sql"] = sql
        await agent.session_manager.set_pending_approval(str(session_id), payload)

    async def _get_agent_or_raise(self, user_key: str):
        """Init agent for user; raise HTTPException(500) if anything is off."""
        try:
            logger.info(f"UseCase: Getting agent for user_key={user_key}")
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e
        if not agent.sessions:
            logger.error("UseCase: Agent initialized but no MCP servers connected")
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )
        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")
        return agent

    def _resolve_project_id_uuid(self, project_id: str | None, share_ctx: dict | None) -> str | None:
        """Validate ``project_id`` as UUID. For forked share sessions whose
        frontend doesn't know the owner's project, fall back to ``share_ctx``."""
        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                    logger.info(f"UseCase: Using project_id={project_id_uuid}")
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID: {project_id!r}, ignoring")
        if project_id_uuid is None and share_ctx and share_ctx.get("project_id"):
            project_id_uuid = share_ctx["project_id"]
            logger.info(f"UseCase: Using share-derived project_id={project_id_uuid}")
        return project_id_uuid

    async def _push_db_to_agents(self, agent, db_url: str, *, label: str) -> None:
        """Push ``db_url`` to the database server (connect_sqlite / primary adapter) and the chart
        server (chart_connect_db). ``label`` is just for log messages."""
        try:
            connect_result = await agent.connect_to_project_db(db_url)
            logger.info(f"UseCase: {label} DB connection result: {connect_result}")
        except Exception as e:
            logger.warning(f"UseCase: {label} DB connect failed: {e}")
        try:
            chart_result = await agent.connect_chart_to_project_db(db_url)
            logger.info(f"UseCase: {label} chart server connection result: {chart_result}")
        except Exception as e:
            logger.warning(f"UseCase: Failed to connect chart server to {label}: {e}")

    async def _push_session_file_to_agents(
        self, agent, db_url: str, *, label: str, allowed_tables: str | None = None
    ) -> None:
        """Push a session-file SQLite as the *session* adapter (does NOT override primary DB).

        Use when the user selected both their primary database and an uploaded file so that
        both can be queried simultaneously.

        Args:
            allowed_tables: Comma-separated table names to expose (only selected files' tables).
        """
        try:
            result = await agent.connect_session_file_db(db_url, allowed_tables=allowed_tables)
            logger.info(f"UseCase: {label} session-file DB connection result: {result}")
        except Exception as e:
            logger.warning(f"UseCase: {label} session-file DB connect failed: {e}")

    async def _auto_connect_project_db(
        self, agent, project_id_uuid: str | None, project_lookup_user: str,
    ) -> str | None:
        """Look up the project's ``db_url`` and push it to MCP servers.
        Returns the resolved db_url (so it can be forwarded to workflows /
        chart-server), or None when no project context applies."""
        if not project_id_uuid or not self._project_repo:
            return None
        try:
            project = await self._project_repo.get_project_by_id(project_id_uuid, project_lookup_user)
        except Exception as e:
            logger.warning(f"UseCase: Failed to auto-connect project database: {e}")
            return None
        if not project or not project.get("db_url"):
            return None
        db_url = project["db_url"]
        if not db_url or db_url.startswith("placeholder://"):
            return None
        logger.info(f"UseCase: Auto-connecting to project database: {db_url}")
        await self._push_db_to_agents(agent, db_url, label="project")
        return db_url

    async def _resolve_or_create_session(
        self, agent, session_id: str | None, project_id_uuid: str | None,
    ) -> str | None:
        """Load the existing session if ``session_id`` is provided; otherwise
        create a new one (bound to ``project_id_uuid`` when inside a project).
        Falls back to whatever ``get_session_info()`` reports as a safety net."""
        loaded = False
        current_session_id: str | None = session_id
        if session_id:
            logger.info(f"UseCase: Attempting to load session: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session: {session_id}")
        if not loaded:
            logger.info(f"UseCase: Creating new session, project_id={project_id_uuid}")
            current_session_id = await agent.session_manager.create_session(
                session_name=None, project_id=project_id_uuid,
            )
        if not current_session_id:
            current_session_id = (await agent.session_manager.get_session_info()).get("session_id") or None
        return current_session_id

    async def _has_session_files(self, current_session_id: str | None, user_key: str) -> bool:
        if not (self._file_usecase and current_session_id and user_key != "anonymous"):
            return False
        try:
            return len(
                await self._file_usecase.get_session_files(current_session_id, user_key)
            ) > 0
        except Exception as e:
            logger.warning("UseCase: failed to inspect session files for RAG gating: %s", e)
            return False

    async def _try_summary_shortcut(
        self, agent, current_session_id: str | None, user_key: str,
        original_user_query: str, use_file_rag: bool,
    ) -> tuple[str, str | None, list[dict], bool, list[dict], bool] | None:
        """Excel-route shortcut: "summarize" intent + exactly one attached
        session file → bypass the tool loop and use ``FileUseCase.summarize_file``.
        Returns the final chat result tuple, or None if the shortcut does not apply."""
        if not (use_file_rag and self._file_usecase and current_session_id and user_key != "anonymous"):
            return None
        if not _looks_like_summary_request(original_user_query):
            return None
        try:
            session_files = await self._file_usecase.get_session_files(current_session_id, user_key)
            if len(session_files) != 1:
                return None
            fid = uuid.UUID(str(session_files[0]["id"]))
            summary_text = await self._file_usecase.summarize_file(fid, user_key)
            try:
                await agent.session_manager.load_session(current_session_id)
            except Exception:
                pass
            await agent.session_manager.add_message("user", original_user_query)
            await agent.session_manager.add_message("assistant", summary_text)
            return summary_text, current_session_id, [], False, [], True
        except Exception as e:
            logger.warning("UseCase: summarize shortcut failed: %s", e)
            return None

    async def _apply_file_rag(
        self, agent, current_session_id: str | None, user_key: str,
        query: str, original_user_query: str,
        use_file_rag: bool, project_db_url: str | None,
        active_file_ids: list[str] | None = None,
    ) -> tuple[str, str | None]:
        """When session-file RAG is enabled: (a) connect MCP servers to the
        session's SQLite file if no project DB was selected, (b) retrieve
        top-k chunks and prepend them as a context block.
        Returns ``(augmented_query, possibly_updated_project_db_url)``."""
        if not (use_file_rag and self._file_usecase and current_session_id and user_key != "anonymous"):
            return query, project_db_url
        try:
            session_sql_url = await self._file_usecase.get_session_sqlite_url(
                current_session_id, user_key
            )
            if session_sql_url and not project_db_url:
                project_db_url = session_sql_url
                await self._push_db_to_agents(agent, session_sql_url, label="session-file")
                try:
                    if "sqlite" in (session_sql_url or "").lower():
                        agent.connection_info = {"engine": "sqlite"}
                    else:
                        agent.connection_info = {"engine": "postgresql"}
                except Exception:
                    pass

            # Pass active_file_ids so the ATTACHED FILES CONTEXT only lists
            # tables from the files the user actually selected.
            _chunks, block = await self._file_usecase.retrieve_relevant_chunks(
                current_session_id, original_user_query, user_key, top_k=8,
                active_file_ids=active_file_ids or None,
            )
            if block:
                return f"{block}\n\nUSER MESSAGE:\n{query}", project_db_url
        except Exception as e:
            logger.warning("UseCase: session file RAG failed: %s", e)
        return query, project_db_url

    async def _seed_share_session_messages(
        self, agent, chat_graph, cfg, share_ctx: dict | None,
    ) -> list[BaseMessage]:
        """Forked share sessions: the snapshot copies ``session.content.messages``
        (JSONB) from the owner, but NOT the LangGraph checkpoint. So on the
        recipient's first turn the graph state would otherwise start empty.
        If the checkpoint really is empty, seed it from the JSONB snapshot so
        the agent sees the owner's transcript. Persistence is unaffected — the
        new turn is appended separately by ``_persist_turn`` after invoke."""
        if share_ctx is None:
            return []
        existing_in_checkpoint: list = []
        try:
            state = await chat_graph.aget_state(cfg)
            if state:
                existing_in_checkpoint = (state.values or {}).get("messages") or []
        except Exception as e:
            # ``aget_state`` raises "Subgraph chat not found" for never-invoked
            # threads — treat that as empty.
            logger.debug(f"UseCase: aget_state for forked session unavailable, treating as empty: {e}")
        if existing_in_checkpoint:
            return []
        seeded: list[BaseMessage] = []
        try:
            snapshot = await agent.session_manager.get_current_messages()
            for m in (snapshot or []):
                role = (m or {}).get("role")
                content = (m or {}).get("content", "")
                if not isinstance(content, str) or not content.strip():
                    continue
                if role == "user":
                    seeded.append(HumanMessage(content=content))
                elif role == "assistant":
                    seeded.append(AIMessage(content=content))
        except Exception as e:
            logger.warning(f"UseCase: Failed to read snapshot for seeding: {e}")
        return seeded

    async def _invoke_chat_graph(
        self, agent, current_session_id: str | None,
        query: str, rag_augmented_query: str,
        project_id_uuid: str | None, user_key: str, project_db_url: str | None,
        share_ctx: dict | None,
        active_file_table_hint: str | None = None,
    ) -> dict:
        """Build the chat-graph input (with optional snapshot seeding for forked
        shares), invoke ``chat_graph.ainvoke`` with the right thread config, and
        return the output dict."""
        chat_graph = await agent.get_chat_graph()
        cfg = chat_checkpoint_config(current_session_id)
        seeded = await self._seed_share_session_messages(agent, chat_graph, cfg, share_ctx)
        input_messages: list[BaseMessage] = [
            *seeded,
            HumanMessage(content=rag_augmented_query),
        ]
        raw_out = await chat_graph.ainvoke(
            {
                "messages": input_messages,
                "project_id": project_id_uuid,
                "user_id": user_key,
                "allowed_db_uri": project_db_url,
                "active_file_table_hint": active_file_table_hint or None,
            },
            config=cfg,
        )
        return dict(raw_out) if isinstance(raw_out, dict) else {}

    async def _persist_turn(self, agent, original_user_query: str, response_text: str) -> None:
        """Append the user + assistant turn to JSONB (UI mirror). The LangGraph
        checkpoint is the source of truth for LLM context and is written by
        ``chat_graph`` itself."""
        if not agent.session_manager:
            return
        if (original_user_query or "").strip():
            await agent.session_manager.add_message("user", original_user_query)
        if (response_text or "").strip():
            await agent.session_manager.add_message("assistant", response_text)

    async def _finalize_chat_turn(
        self, agent, out: dict, current_session_id: str | None,
        user_key: str, original_user_query: str,
    ) -> tuple[str, str | None, list[dict], bool, list[dict], bool]:
        """Parse chat-graph output, attach SQL/Excel post-processing markers,
        persist the turn + any pending approval, and return the final tuple
        shape expected by the HTTP layer."""
        response_text = str(out.get("response", ""))
        agent_id = str(out.get("agent_id", "unknown"))
        pending_workflow_resume = bool(out.get("pending_workflow_resume"))
        workflow_state = out.get("workflow_state") or {}
        warnings: list[dict] = []
        success = bool(out.get("success", True))
        if isinstance(workflow_state, dict):
            ws_warnings = workflow_state.get("warnings") or []
            if isinstance(ws_warnings, list):
                warnings = [w for w in ws_warnings if isinstance(w, dict)]
            success = bool(workflow_state.get("success", success))
            ws_output = workflow_state.get("output") or {}
            if isinstance(ws_output, dict) and ws_output.get("type") in {"error", "needs_input"}:
                success = False

        session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
        current_session_id = session_info.get("session_id") if session_info else current_session_id

        sql_preview = self._extract_last_mutation_sql_block(response_text)
        if sql_preview:
            action_id = str(uuid.uuid4())
            response_text = self._attach_sql_action_id_marker(response_text, action_id)

        response_text = await self._maybe_persist_excel_export_in_assistant_reply(
            response_text, current_session_id, user_key,
        )

        logger.info(
            "UseCase: Query processed, session_id=%s, agent=%s, success=%s",
            current_session_id, agent_id, success,
        )

        await self._persist_turn(agent, original_user_query, response_text)

        tool_events = out.get("tool_events") or []
        if not isinstance(tool_events, list):
            tool_events = []

        await self._persist_pending_approval_from_workflow(
            agent,
            current_session_id,
            pending_workflow_resume=pending_workflow_resume,
            workflow_state=(workflow_state if isinstance(workflow_state, dict) else None),
            tool_events=tool_events,
        )

        return response_text, current_session_id, tool_events, pending_workflow_resume, warnings, success

    async def chat(
        self, user_key: str, message: str, session_id: str | None, project_id: str | None = None,
        active_file_ids: list[str] | None = None,
    ) -> tuple[str, str | None, list[dict], bool, list[dict], bool]:
        logger.info(f"UseCase: Processing chat message, user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (message or "").strip()
        if not query:
            logger.error("UseCase: Message is required but was empty")
            raise HTTPException(status_code=400, detail="Message is required")

        # Share-permission gating: reject view_only and inject the read_data note.
        share_ctx = await self._get_share_context(session_id, user_key)
        share_permission = share_ctx["permission"] if share_ctx else None
        if share_permission == "view_only":
            raise HTTPException(
                status_code=403,
                detail="This session is shared with view-only access; you cannot send messages.",
            )
        # Keep the original user text (pre system-note injection) for history.
        # Upload markers stay so the frontend can recover attached filenames on reload.
        original_user_query = query
        if share_permission == "read_data":
            query = f"{_READ_DATA_SYSTEM_NOTE}\n\nUser message: {query}"
        # For forked shares, projects belong to the owner; look them up under the owner's id.
        project_lookup_user = share_ctx["owner_user_id"] if share_ctx else user_key

        agent = await self._get_agent_or_raise(user_key)

        project_id_uuid = self._resolve_project_id_uuid(project_id, share_ctx)
        project_db_url = await self._auto_connect_project_db(
            agent, project_id_uuid, project_lookup_user,
        )
        # Thesis rule: project sessions use SQLite; non-project sessions use PostgreSQL.
        try:
            agent.connection_info = {"engine": "sqlite" if project_id_uuid else "postgresql"}
        except Exception:
            pass

        current_session_id = await self._resolve_or_create_session(
            agent, session_id, project_id_uuid,
        )

        # --- Active data source from UI selector ---
        # active_file_ids may contain '__primary_db__' and/or actual file UUIDs.
        ids = list(active_file_ids or [])
        user_selected_primary_db = "__primary_db__" in ids
        file_ids_selected = [fid for fid in ids if fid != "__primary_db__"]

        active_file_table_hint: str | None = None   # comma-separated table names for multi-file
        active_file_sqlite_url: str | None = None

        # file_meta_for_context: list of (filename, sqlite_table_name) for selected files
        # used later to inject a table-name context block when RAG is skipped (DB+file mode).
        file_meta_for_context: list[tuple[str, str]] = []

        if file_ids_selected and self._file_usecase and current_session_id and user_key != "anonymous":
            table_hints: list[str] = []
            sqlite_url_seen: str | None = None
            from internal.features.file.service import _sqlite_engine_url_from_stored
            for fid in file_ids_selected:
                try:
                    file_row = await self._file_usecase.get_file(uuid.UUID(fid), user_key)
                    if file_row:
                        tname = file_row.get("sqlite_table_name")
                        fname = file_row.get("filename") or ""
                        if tname:
                            table_hints.append(str(tname))
                            file_meta_for_context.append((str(fname), str(tname)))
                        raw_path = file_row.get("sqlite_db_path")
                        if raw_path and not sqlite_url_seen:
                            sqlite_url_seen = _sqlite_engine_url_from_stored(str(raw_path))
                except Exception as e:
                    logger.warning("UseCase: failed to resolve active_file_id=%s: %s", fid, e)
            if table_hints:
                active_file_sqlite_url = sqlite_url_seen
                # Only force a table hint when the user chose file(s) WITHOUT the primary DB.
                # When both DB + file(s) are selected, leave table_hint=None so the LLM
                # sees all tables from both sources via list_tables and can query freely.
                if not user_selected_primary_db:
                    active_file_table_hint = ", ".join(table_hints)
            logger.info(
                "UseCase: active_file_ids=%s → table_hint=%s sqlite_url=%s",
                file_ids_selected, active_file_table_hint, active_file_sqlite_url,
            )

        # RAG gating: should we splice retrieved file chunks into the user turn?
        has_session_files = await self._has_session_files(current_session_id, user_key)
        has_file_data_intent, decision_source, heuristic_state, llm_latency_ms = (
            await self._resolve_file_data_intent(
                original_user_query,
                should_try_llm=has_session_files,
            )
        )
        # Skip RAG entirely when user has selected their primary DB — don't override with session SQLite.
        use_file_rag = (not user_selected_primary_db) and has_session_files and has_file_data_intent
        logger.info(
            "UseCase: RAG gating "
            "has_file_data_intent=%s has_session_files=%s "
            "use_file_rag=%s decision_source=%s heuristic_state=%s llm_latency_ms=%s "
            "has_file_usecase=%s",
            has_file_data_intent,
            has_session_files,
            use_file_rag,
            decision_source,
            heuristic_state,
            f"{llm_latency_ms:.1f}" if isinstance(llm_latency_ms, float) else "n/a",
            bool(self._file_usecase),
        )

        shortcut = await self._try_summary_shortcut(
            agent, current_session_id, user_key, original_user_query, use_file_rag,
        )
        if shortcut is not None:
            return shortcut

        # Connect the selected file's SQLite to the MCP server.
        if active_file_sqlite_url:
            if user_selected_primary_db:
                # Both DB + file selected → attach file as session adapter (keeps primary intact).
                # Pass the selected table names so list_tables only surfaces those tables,
                # not every table that has ever been uploaded to this session's SQLite.
                allowed_tables_str = ", ".join(table_hints) if table_hints else None
                await self._push_session_file_to_agents(
                    agent, active_file_sqlite_url,
                    label="active-file-session",
                    allowed_tables=allowed_tables_str,
                )
            else:
                # File-only selected → connect as primary (no user DB to protect).
                await self._push_db_to_agents(agent, active_file_sqlite_url, label="active-file")
                if not project_db_url:
                    project_db_url = active_file_sqlite_url
        else:
            # No file selected this turn — disconnect any leftover session adapter so
            # list_tables / queries don't accidentally surface tables from a previous file.
            try:
                await agent.disconnect_session_file_db()
            except Exception as _e:
                logger.debug("UseCase: disconnect_session_file_db skipped: %s", _e)

        rag_augmented_query, project_db_url = await self._apply_file_rag(
            agent, current_session_id, user_key, query, original_user_query,
            use_file_rag, project_db_url,
            active_file_ids=file_ids_selected or None,
        )

        # When DB + file(s) selected, RAG is skipped so LLM has no knowledge of the
        # session-file table names. Inject a minimal hint so it uses exact table names.
        if user_selected_primary_db and file_meta_for_context and rag_augmented_query == query:
            table_lines = "\n".join(
                f"  - file: {fname}  →  sqlite table: `{tname}`"
                for fname, tname in file_meta_for_context
            )
            hint_block = (
                "[SESSION FILE TABLES — use these EXACT table names in SQL queries]\n"
                f"{table_lines}\n"
                "[/SESSION FILE TABLES]"
            )
            rag_augmented_query = f"{hint_block}\n\nUSER MESSAGE:\n{query}"
            logger.info("UseCase: injected session file table hints into query (DB+file mode)")

        logger.info(f"UseCase: Processing query: {query[:100]}...")
        try:
            out = await self._invoke_chat_graph(
                agent, current_session_id, query, rag_augmented_query,
                project_id_uuid, user_key, project_db_url,
                share_ctx,
                active_file_table_hint=active_file_table_hint,
            )
            return await self._finalize_chat_turn(
                agent, out, current_session_id, user_key, original_user_query,
            )
        except Exception as e:
            logger.error(f"UseCase: Error processing query: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}") from e

    async def chat_stream(
        self,
        user_key: str,
        message: str,
        session_id: str | None,
        project_id: str | None = None,
        active_file_ids: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """Streaming variant of ``chat`` — yields SSE-formatted strings.

        Emits ``stage`` events as workflow stages run and a final ``final``
        event with the complete payload (same shape as ``chat``'s response).
        """
        # asyncio.Queue handles the producer/consumer hop between the chat task
        # (which calls progress emit) and this generator (which yields to HTTP).
        queue: asyncio.Queue = asyncio.Queue()

        async def progress_cb(event: dict) -> None:
            await queue.put(event)

        async def run_chat_task() -> None:
            token = set_progress_callback(progress_cb)
            # Pin this user's orchestrator for the whole turn so the LRU/TTL
            # eviction sweep never tears down its subprocesses mid-request
            # (covers client-disconnect cancellation too — finally still runs).
            self._agent_repo.mark_in_use(user_key)
            try:
                response_text, sid, tool_events, pending, warnings, success = await self.chat(
                    user_key, message, session_id, project_id, active_file_ids
                )
                await queue.put({
                    "type": "final",
                    "data": {
                        "response": response_text,
                        "session_id": sid,
                        "tool_events": tool_events,
                        "pending_workflow_resume": pending,
                        "warnings": warnings,
                        "success": success,
                    },
                })
            except HTTPException as he:
                await queue.put({"type": "error", "status_code": he.status_code, "message": str(he.detail)})
            except Exception as e:
                logger.exception("chat_stream: chat task failed: %s", e)
                await queue.put({"type": "error", "status_code": 500, "message": str(e)})
            finally:
                self._agent_repo.mark_done(user_key)
                reset_progress_callback(token)
                await queue.put(None)  # sentinel: end of stream

        task = asyncio.create_task(run_chat_task())

        try:
            # Initial event so the UI can switch to "streaming" state immediately.
            yield _sse_format({"type": "started"})
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield _sse_format(event)
        finally:
            # If the client disconnected, cancel the chat task to free resources.
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    async def workflow_resume(
        self,
        user_key: str,
        session_id: str,
        approved: bool,
        project_id: str | None = None,
        user_visible_message: str | None = None,
    ) -> tuple[str, str | None, list[dict], bool, list[dict], bool]:
        """Resume database LangGraph human-in-the-loop (same session / DB connect as chat)."""
        sid = (session_id or "").strip()
        if not sid:
            raise HTTPException(status_code=400, detail="session_id is required")

        share_ctx = await self._get_share_context(sid, user_key)
        share_permission = share_ctx["permission"] if share_ctx else None
        if share_permission == "view_only":
            raise HTTPException(
                status_code=403,
                detail="This session is shared with view-only access; you cannot resume workflows.",
            )
        if share_permission == "read_data" and approved:
            # Approving a workflow resume runs whatever was previewed (mutation SQL,
            # schema changes, etc). Read-only recipients cannot approve.
            raise HTTPException(
                status_code=403,
                detail="Read-only share cannot approve workflows that change data or schema.",
            )
        project_lookup_user = share_ctx["owner_user_id"] if share_ctx else user_key

        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent (workflow_resume): {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions or not agent.session_manager:
            raise HTTPException(status_code=500, detail="Agent is not ready")

        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID in workflow_resume: {project_id!r}, ignoring")

        if project_id_uuid is None and share_ctx and share_ctx.get("project_id"):
            project_id_uuid = share_ctx["project_id"]

        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, project_lookup_user)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    if db_url and not db_url.startswith("placeholder://"):
                        await agent.connect_to_project_db(db_url)
                        try:
                            await agent.connect_chart_to_project_db(db_url)
                        except Exception as e:
                            logger.warning(f"UseCase: Chart connect failed in workflow_resume: {e}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database in workflow_resume: {e}")

        # Thesis rule: project sessions use SQLite; non-project sessions use PostgreSQL.
        try:
            agent.connection_info = {"engine": "sqlite" if project_id_uuid else "postgresql"}
        except Exception:
            pass

        loaded = await agent.session_manager.load_session(sid)
        if not loaded:
            raise HTTPException(status_code=400, detail="Session not found or could not be loaded")

        if not hasattr(agent, "resume_workflow"):
            raise HTTPException(status_code=501, detail="Workflow resume is not supported for this agent")

        uvm = (user_visible_message or "").strip()
        if uvm and agent.session_manager:
            await agent.session_manager.add_message("user", uvm)
        result = await agent.resume_workflow(sid, approved=approved)
        response_text = str(result.get("response", ""))
        tool_events = result.get("tool_events") or []
        if not isinstance(tool_events, list):
            tool_events = []
        pending_workflow_resume = bool(result.get("pending_workflow_resume"))
        workflow_state = result.get("workflow_state") or {}
        warnings: list[dict] = []
        success = True
        if isinstance(workflow_state, dict):
            ws_warnings = workflow_state.get("warnings") or []
            if isinstance(ws_warnings, list):
                warnings = [w for w in ws_warnings if isinstance(w, dict)]
            success = bool(workflow_state.get("success", True))

        sql_preview = self._extract_last_mutation_sql_block(response_text)
        if sql_preview:
            action_id = str(uuid.uuid4())
            response_text = self._attach_sql_action_id_marker(response_text, action_id)

        response_text = await self._maybe_persist_excel_export_in_assistant_reply(
            response_text, sid, user_key
        )

        if (response_text or "").strip():
            await agent.session_manager.add_message("assistant", response_text)

        try:
            await agent.merge_resume_into_chat_checkpoint(sid, uvm, response_text)
        except Exception as e:
            logger.warning("UseCase: merge_resume_into_chat_checkpoint failed: %s", e)

        session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
        current_session_id = session_info.get("session_id") if session_info else sid

        # Persist new pending approval payload when resume leads to the next interrupt (e.g. schema gate → SQL gate).
        await self._persist_pending_approval_from_workflow(
            agent,
            current_session_id,
            pending_workflow_resume=pending_workflow_resume,
            workflow_state=(workflow_state if isinstance(workflow_state, dict) else None),
            tool_events=tool_events,
        )
        return response_text, current_session_id, tool_events, pending_workflow_resume, warnings, success

    async def execute_sql(
        self,
        user_key: str,
        sql: str,
        action_id: str | None,
        session_id: str | None,
        project_id: str | None = None,
        lock_only: bool = False,
        lock_state: str | None = None,
    ) -> tuple[str, str | None, list[dict], bool, list[dict], bool]:
        """
        Execute a raw SQL statement that was previously previewed to the user.
        This reuses the same agent + project DB auto-connect + session logic as chat().
        """
        logger.info(f"UseCase: Executing SQL for user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (sql or "").strip()
        if not query:
            logger.error("UseCase: SQL is required but was empty")
            raise HTTPException(status_code=400, detail="SQL is required")

        # Share-permission gating before any DB work.
        share_ctx = await self._get_share_context(session_id, user_key)
        share_permission = share_ctx["permission"] if share_ctx else None
        if share_permission == "view_only":
            raise HTTPException(
                status_code=403,
                detail="This session is shared with view-only access; you cannot execute SQL.",
            )
        if share_permission == "read_data" and not lock_only and not _is_read_only_sql(query):
            raise HTTPException(
                status_code=403,
                detail="Read-only share: only SELECT/WITH/SHOW/DESCRIBE/EXPLAIN queries are allowed.",
            )
        project_lookup_user = share_ctx["owner_user_id"] if share_ctx else user_key

        try:
            logger.info(f"UseCase: Getting agent for user_key={user_key} (execute_sql)")
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent (execute_sql): {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions:
            logger.error("UseCase: Agent initialized but no MCP servers connected (execute_sql)")
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )

        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent (execute_sql)")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")

        # Validate project_id as UUID (from projects.id) if provided
        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                    logger.info(f"UseCase: Using project_id={project_id_uuid} (execute_sql)")
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID in execute_sql: {project_id!r}, ignoring")

        if project_id_uuid is None and share_ctx and share_ctx.get("project_id"):
            project_id_uuid = share_ctx["project_id"]
            logger.info(f"UseCase: Using share-derived project_id={project_id_uuid} (execute_sql)")

        # Auto-connect database based on context (same as chat)
        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, project_lookup_user)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    if db_url and not db_url.startswith("placeholder://"):
                        logger.info(f"UseCase: Auto-connecting to project database (execute_sql): {db_url}")
                        connect_result = await agent.connect_to_project_db(db_url)
                        logger.info(f"UseCase: Database connection result (execute_sql): {connect_result}")
                        try:
                            await agent.connect_chart_to_project_db(db_url)
                        except Exception as e:
                            logger.warning(f"UseCase: Chart connect failed in execute_sql: {e}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database in execute_sql: {e}")

        # Thesis rule: project sessions use SQLite; non-project sessions use PostgreSQL.
        try:
            agent.connection_info = {"engine": "sqlite" if project_id_uuid else "postgresql"}
        except Exception:
            pass

        # Load or create session (so history / project context is consistent)
        loaded = False
        if session_id:
            logger.info(f"UseCase: Attempting to load session in execute_sql: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session in execute_sql: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session in execute_sql: {session_id}")

        if not loaded:
            logger.info(f"UseCase: Creating new session for execute_sql, project_id={project_id_uuid}")
            await agent.session_manager.create_session(session_name=None, project_id=project_id_uuid)

        session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
        current_session_id = session_info.get("session_id") if session_info else None

        # lock_only path: persist one-time lock in DB without executing SQL.
        if lock_only and current_session_id:
            if not (action_id or "").strip():
                raise HTTPException(status_code=400, detail="action_id is required for SQL action locking")
            state_to_store = (lock_state or "executed").strip().lower()
            if state_to_store not in {"executed", "cancelled"}:
                state_to_store = "executed"
            if state_to_store == "cancelled" and hasattr(agent, "resume_workflow"):
                pend = await agent.session_manager.get_pending_approval(current_session_id)
                if isinstance(pend, dict) and pend.get("kind") == "workflow_langgraph_interrupt":
                    await agent.resume_workflow(current_session_id, approved=False)
            await agent.session_manager.set_sql_action_state(current_session_id, action_id, state_to_store)
            logger.info(f"UseCase: SQL action locked (lock_only={state_to_store}), session_id={current_session_id}, action_id={action_id}")
            return "SQL action locked", current_session_id, [], False, [], True

        # Guardrail: CREATE TABLE only with matching pending approval (legacy or LangGraph SQL gate).
        is_create_table = bool(re.match(r"^\s*CREATE\s+TABLE\b", query, flags=re.IGNORECASE))
        if is_create_table:
            session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
            current_session_id = session_info.get("session_id") if session_info else None
            pending = await agent.session_manager.get_pending_approval(current_session_id) if current_session_id else None
            if not pending:
                raise HTTPException(
                    status_code=400,
                    detail="CREATE TABLE is blocked: no pending schema approval found. Please confirm schema first.",
                )

            pending_kind = str(pending.get("kind") or "")
            pending_sql = str(pending.get("sql") or "").strip()
            normalized_query = query.rstrip(";").strip()
            normalized_pending_sql = pending_sql.rstrip(";").strip()

            if pending_kind == "create_table_after_schema_confirm":
                if normalized_query != normalized_pending_sql:
                    raise HTTPException(
                        status_code=400,
                        detail="CREATE TABLE is blocked: SQL does not match the approved schema preview.",
                    )
            elif (
                pending_kind == "workflow_langgraph_interrupt"
                and str(pending.get("interrupt_stage") or "") == "SQL_PREVIEW"
            ):
                if not pending_sql or normalized_query != normalized_pending_sql:
                    raise HTTPException(
                        status_code=400,
                        detail="CREATE TABLE is blocked: SQL does not match the workflow preview.",
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="CREATE TABLE is blocked: pending approval kind is invalid for table creation.",
                )

        logger.info(f"UseCase: Executing SQL (first 200 chars): {query[:200]}...")
        try:
            # HybridOrchestrator may have approve_and_execute method
            if hasattr(agent, 'approve_and_execute'):
                session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
                current_session_id = session_info.get("session_id") if session_info else None
                result = await agent.approve_and_execute(
                    session_id=current_session_id,
                    approved=True,
                    sql=query,
                )

                # Approval preview state is stored in SessionManager (persisted).
                # If the server reloaded or state is missing, fallback to executing the SQL
                # that the frontend already extracted from the preview message.
                approve_result_text = str(result.get("response", "")) if isinstance(result, dict) else str(result)
                approve_missing_state = approve_result_text.strip().startswith("Session ") and " not found" in approve_result_text
                approve_no_sql = (approve_result_text.strip() == "No SQL to execute")
                ws_output = {}
                if isinstance(result, dict):
                    ws = result.get("workflow_state") or {}
                    if isinstance(ws, dict):
                        ws_output = ws.get("output") or {}
                still_preview = (
                    isinstance(ws_output, dict)
                    and ws_output.get("type") == "sql_preview"
                    and not any(
                        (e or {}).get("type") == "sql_execution"
                        for e in (result.get("tool_events") or [])
                        if isinstance(e, dict)
                    )
                )
                if approve_missing_state or approve_no_sql or still_preview:
                    logger.warning(
                        "UseCase: approval path unusable (%s), falling back to direct execute_sql. session_id=%s",
                        (
                            "no session"
                            if approve_missing_state
                            else ("still preview" if still_preview else "no pending sql")
                        ),
                        current_session_id,
                    )
                    result = await agent.execute_sql(query)
            else:
                # Legacy: call execute_sql directly
                result = await agent.execute_sql(query)
                session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
                current_session_id = session_info.get("session_id") if session_info else None

            pending_workflow_resume = False
            warnings: list[dict] = []
            success = True
            if isinstance(result, dict):
                result_text = str(result.get("response", ""))
                tool_events = result.get("tool_events") or []
                if not isinstance(tool_events, list):
                    tool_events = []
                pending_workflow_resume = bool(result.get("pending_workflow_resume"))
                workflow_state = result.get("workflow_state") or {}
                if isinstance(workflow_state, dict):
                    ws_warnings = workflow_state.get("warnings") or []
                    if isinstance(ws_warnings, list):
                        warnings = [w for w in ws_warnings if isinstance(w, dict)]
                    success = bool(workflow_state.get("success", True))
                    ws_output = workflow_state.get("output") or {}
                    if isinstance(ws_output, dict) and ws_output.get("type") == "error":
                        success = False
            else:
                result_text = str(result)
                tool_events = []
                warnings = []
                success = True

            if current_session_id and (action_id or "").strip():
                await agent.session_manager.set_sql_action_state(current_session_id, action_id, "executed")

            result_text = await self._maybe_persist_excel_export_in_assistant_reply(
                result_text, current_session_id, user_key
            )

            # Persist assistant execution result so it survives page reload/history fetch.
            if agent.session_manager and (result_text or "").strip():
                await agent.session_manager.add_message("assistant", result_text)

            if success:
                logger.info(f"UseCase: SQL executed successfully, session_id={current_session_id}")
            else:
                logger.warning(
                    "UseCase: SQL execution failed, session_id=%s, response=%s",
                    current_session_id,
                    (result_text or "")[:300],
                )
            return result_text, current_session_id, tool_events, pending_workflow_resume, warnings, success
        except Exception as e:
            logger.error(f"UseCase: Error executing SQL: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to execute SQL: {str(e)}") from e

    async def connect_external_db(
        self,
        user_key: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> tuple[bool, str]:
        """Connect the database agent to an external PostgreSQL database."""
        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            return False, f"Failed to initialize agent: {e}"

        result = await agent.connect_external_db(
            host=host, port=port, database=database,
            username=username, password=password,
        )
        success = "failed" not in result.lower() and "error" not in result.lower() and "not found" not in result.lower()
        return success, result

    async def disconnect_external_db(self, user_key: str) -> tuple[bool, str]:
        """Disconnect the database agent from its current external database."""
        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            return False, f"Failed to initialize agent: {e}"

        result = await agent.disconnect_external_db()
        return True, result

    async def check_db_connection(self, user_key: str) -> tuple[bool, str]:
        """Return (True, message) if the database agent has an active connection."""
        try:
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            return False, f"Failed to initialize agent: {e}"

        result = await agent.check_db_connection()
        connected = "not connected" not in result.lower() and "error" not in result.lower()
        return connected, result
