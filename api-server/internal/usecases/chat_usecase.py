from __future__ import annotations

import asyncio
import json as _json
import logging
import re
import time
import uuid
from typing import AsyncIterator, Optional

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository
from internal.repositories.chat_share_repository import ChatShareRepository
from internal.repositories.project_repository import ProjectRepository
from internal.usecases.file_usecase import FileUseCase

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from mcp_agent.graph.chat_graph import chat_checkpoint_config, langchain_messages_to_session_rows
from mcp_agent.progress import set_progress_callback, reset_progress_callback

logger = logging.getLogger(__name__)


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
    # Vietnamese
    if any(w in q for w in ("tóm tắt", "tom tat", "tổng quan", "tong quan", "nội dung", "noi dung")):
        return True
    return False

# Permission ladder: view_only < read_data < edit_data. A request is allowed
# when the caller's rank ≥ the rank of the access_level the IntentResult
# carries. The IntentService is the single source of truth for ``access_level``
# (derived deterministically from ``route``); chat_usecase only enforces.
_PERMISSION_RANK = {"view_only": 0, "read_data": 1, "edit_data": 2}


def _is_access_allowed(required: str | None, have: str) -> bool:
    """True if caller's permission ``have`` covers the required ``access_level``."""
    if not required:
        # Classifier didn't return an access_level (clarification needed, or
        # error). Let the request through; downstream gates still apply.
        return True
    return _PERMISSION_RANK.get(have, -1) >= _PERMISSION_RANK.get(required, 99)

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


class ChatUseCase:
    def __init__(
        self,
        agent_repo: AgentRepository,
        project_repo: Optional[ProjectRepository] = None,
        share_repo: Optional[ChatShareRepository] = None,
        file_usecase: Optional[FileUseCase] = None,
    ):
        self._agent_repo = agent_repo
        self._project_repo = project_repo
        self._share_repo = share_repo
        self._file_usecase = file_usecase
        # In-memory guest-token cache to dedupe rapid mint calls (page reload
        # storms, embed-sdk timer overlaps). Superset rate-limits the
        # /api/v1/security/guest_token/ endpoint to 50 rps; without this,
        # zombie timers from old mounts can lock the whole app out for the
        # current minute. Key = (user_key, embedded_uuid). TTL kept under the
        # token's actual JWT expiry so we never serve a stale token.
        self._guest_token_cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._guest_token_cache_safety_seconds = 30

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

    async def chat(
        self, user_key: str, message: str, session_id: str | None, project_id: str | None = None
    ) -> tuple[str, str | None, list[dict], bool, list[dict], bool]:
        logger.info(f"UseCase: Processing chat message, user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (message or "").strip()
        if not query:
            logger.error("UseCase: Message is required but was empty")
            raise HTTPException(status_code=400, detail="Message is required")

        # Share-permission gating: if this session is a forked share, enforce permission.
        share_ctx = await self._get_share_context(session_id, user_key)
        share_permission = share_ctx["permission"] if share_ctx else None
        if share_permission == "view_only":
            raise HTTPException(
                status_code=403,
                detail="This session is shared with view-only access; you cannot send messages.",
            )
        # Keep the original user text (pre system-note injection) so we can
        # write it back into history. We *keep* upload markers here so the
        # frontend can recover the attached filename on reload (it strips
        # markers for display and parses them for the attachment chip).
        original_user_query = query
        if share_permission == "read_data":
            # Prepend a system note so the agent refuses write proposals.
            query = f"{_READ_DATA_SYSTEM_NOTE}\n\nUser message: {query}"

        # When the session is a forked share, projects belong to the owner, not
        # the caller — use the owner's user_id when looking up the project's db_url.
        project_lookup_user = share_ctx["owner_user_id"] if share_ctx else user_key

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

        # Đảm bảo có SessionManager
        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")

        # Single-shot intent classification. The result is reused downstream
        # by passing it into the chat graph state — orchestrator's
        # _parse_intent_node detects ``pre_classified_intent`` and skips its
        # own LLM call. We always classify (not only for forked sessions) so
        # owner sessions also avoid the duplicate.
        pre_classified_intent: dict | None = None
        if hasattr(agent, "classify_intent"):
            try:
                history_msgs = await agent.session_manager.get_current_messages()
            except Exception:
                history_msgs = []
            try:
                pre_classified_intent = await agent.classify_intent(
                    original_user_query,
                    conversation_context=history_msgs,
                )
            except Exception as e:
                logger.warning(f"UseCase: Intent classification failed, falling back to in-graph classification: {e}")
                pre_classified_intent = None

        # Share-permission gate using the intent's access_level. Only enforced
        # for forked share sessions; owner sessions don't need this check.
        if share_ctx is not None and pre_classified_intent:
            required = pre_classified_intent.get("access_level")
            if not _is_access_allowed(required, share_permission or "view_only"):
                route = pre_classified_intent.get("route")
                logger.info(
                    "UseCase: Rejecting forked-session request: route=%s required=%s, have=%s",
                    route, required, share_permission,
                )
                rejection_text = (
                    f"This shared chat is in {share_permission!r} mode; "
                    f"the request needs {required!r} access (route={route!r})."
                )
                # Persist the user's question + the rejection into JSONB so
                # they survive a page reload. Without this, the bubbles only
                # exist in the client's React state and disappear on refresh.
                try:
                    if session_id and await agent.session_manager.load_session(session_id):
                        if (original_user_query or "").strip():
                            await agent.session_manager.add_message("user", original_user_query)
                        await agent.session_manager.add_message(
                            "assistant", f"Error: {rejection_text}"
                        )
                except Exception as e:
                    logger.warning(
                        f"UseCase: Failed to persist rejection turn to session: {e}"
                    )
                raise HTTPException(status_code=403, detail=rejection_text)

        # Validate project_id as UUID (from projects.id) if provided
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

        # Forked share sessions: recipient's frontend may not know the owner's
        # project_id (it isn't in their local project list). Derive from share.
        if project_id_uuid is None and share_ctx and share_ctx.get("project_id"):
            project_id_uuid = share_ctx["project_id"]
            logger.info(f"UseCase: Using share-derived project_id={project_id_uuid}")

        # Auto-connect database based on context:
        # - In project: connect to project's SQLite .db file
        # - Outside project: leave as-is (user manages PostgreSQL connection manually via chat)
        # ``project_db_url`` is captured for forwarding to workflows so Superset can scope
        # by project_id without re-querying database_agent (Phase 1 of scoping refactor).
        project_db_url: str | None = None
        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, project_lookup_user)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    # Only auto-connect if it's a SQLite path (not placeholder)
                    if db_url and not db_url.startswith("placeholder://"):
                        project_db_url = db_url
                        logger.info(f"UseCase: Auto-connecting to project database: {db_url}")
                        connect_result = await agent.connect_to_project_db(db_url)
                        logger.info(f"UseCase: Database connection result: {connect_result}")

                        # Also register the project database in Superset for visualization.
                        # Project-scoped name uses the UUID directly (single source of truth
                        # for downstream MCP tool-level enforcement).
                        try:
                            superset_result = await agent.connect_project_to_superset(
                                project_id=str(project_id_uuid),
                                db_url=db_url,
                                project_name="",
                            )
                            logger.info(f"UseCase: Superset registration result: {superset_result}")
                        except Exception as e:
                            logger.warning(f"UseCase: Failed to register project in Superset: {e}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database: {e}")

        # Thesis rule: project sessions use SQLite; non-project sessions use PostgreSQL.
        try:
            agent.connection_info = {"engine": "sqlite" if project_id_uuid else "postgresql"}
        except Exception:
            pass

        # Nếu có session_id → cố gắng load session đó
        loaded = False
        current_session_id: str | None = session_id
        if session_id:
            logger.info(f"UseCase: Attempting to load session: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session: {session_id}")

        # Nếu không có session_id hoặc load thất bại:
        # - Nếu đang trong project (project_id_uuid) → tạo session mới gắn với project đó
        # - Nếu không có project → tạo session mới global cho user
        if not loaded:
            logger.info(f"UseCase: Creating new session, project_id={project_id_uuid}")
            current_session_id = await agent.session_manager.create_session(session_name=None, project_id=project_id_uuid)

        # Important: pass the *same* session_id through to Orchestrator so that
        # the "preview/approval" flow can find the stored SQL state later.
        if not current_session_id:
            # Should never happen, but keep it safe: fallback to the value inside session_manager.
            current_session_id = (await agent.session_manager.get_session_info()).get("session_id") or None

        # Shortcut: if user asks to summarize and there is exactly one attached file
        # in the session, use FileUseCase.summarize_file (RAG-style) instead of routing
        # to Excel/DB agents (which may require file paths/markers).
        if self._file_usecase and current_session_id and user_key != "anonymous":
            try:
                if _looks_like_summary_request(original_user_query):
                    session_files = await self._file_usecase.get_session_files(current_session_id, user_key)
                    if len(session_files) == 1:
                        fid = uuid.UUID(str(session_files[0]["id"]))
                        summary_text = await self._file_usecase.summarize_file(fid, user_key)
                        # Persist the turn as a normal chat exchange.
                        try:
                            await agent.session_manager.load_session(current_session_id)
                        except Exception:
                            pass
                        await agent.session_manager.add_message("user", original_user_query)
                        await agent.session_manager.add_message("assistant", summary_text)
                        return summary_text, current_session_id, [], False, [], True
            except Exception as e:
                logger.warning("UseCase: summarize shortcut failed: %s", e)

        rag_augmented_query = query
        if self._file_usecase and current_session_id and user_key != "anonymous":
            try:
                session_sql_url = await self._file_usecase.get_session_sqlite_url(
                    current_session_id, user_key
                )
                if session_sql_url and not project_db_url:
                    project_db_url = session_sql_url
                    try:
                        await agent.connect_to_project_db(session_sql_url)
                    except Exception as e:
                        logger.warning("UseCase: session-file DB connect failed: %s", e)
                    try:
                        if "sqlite" in (session_sql_url or "").lower():
                            agent.connection_info = {"engine": "sqlite"}
                        else:
                            agent.connection_info = {"engine": "postgresql"}
                    except Exception:
                        pass

                _chunks, block = await self._file_usecase.retrieve_relevant_chunks(
                    current_session_id, original_user_query, user_key, top_k=8
                )
                if block:
                    rag_augmented_query = f"{block}\n\nUSER MESSAGE:\n{query}"
            except Exception as e:
                logger.warning("UseCase: session file RAG failed: %s", e)

        logger.info(f"UseCase: Processing query: {query[:100]}...")
        try:
            # Chat graph (MessagesState + checkpoint_ns=chat) wraps Orchestrator as one node.
            chat_graph = await agent.get_chat_graph()
            cfg = chat_checkpoint_config(current_session_id)

            # Forked share sessions: the snapshot copies session.content.messages
            # (JSONB) from the owner, but NOT the LangGraph checkpoint. So on
            # the recipient's first turn here, the graph state would otherwise
            # start empty and the agent wouldn't see the owner's transcript at
            # all. Seed the graph input with the snapshot so the agent has
            # context. We append-to-JSONB separately after invoke (see
            # ``add_message`` calls below), so seeding only feeds the agent —
            # it does not affect persistence.
            seeded_messages: list[BaseMessage] = []
            if share_ctx is not None:
                # Step 1: figure out whether the checkpoint already has messages
                # for this thread. ``aget_state`` raises "Subgraph chat not
                # found" for never-invoked threads — treat that as empty.
                existing_in_checkpoint: list = []
                try:
                    state = await chat_graph.aget_state(cfg)
                    if state:
                        existing_in_checkpoint = (state.values or {}).get("messages") or []
                except Exception as e:
                    logger.debug(f"UseCase: aget_state for forked session unavailable, treating as empty: {e}")

                # Step 2: only seed when the checkpoint is empty. Otherwise the
                # reducer would duplicate snapshot messages on top of what the
                # checkpoint already has.
                if not existing_in_checkpoint:
                    try:
                        snapshot = await agent.session_manager.get_current_messages()
                        for m in (snapshot or []):
                            role = (m or {}).get("role")
                            content = (m or {}).get("content", "")
                            if not isinstance(content, str) or not content.strip():
                                continue
                            if role == "user":
                                seeded_messages.append(HumanMessage(content=content))
                            elif role == "assistant":
                                seeded_messages.append(AIMessage(content=content))
                    except Exception as e:
                        logger.warning(f"UseCase: Failed to read snapshot for seeding: {e}")

            input_messages: list[BaseMessage] = [
                *seeded_messages,
                HumanMessage(content=rag_augmented_query),
            ]
            # If we injected RAG context into the user turn, the single-shot
            # pre-classification (computed on the raw query earlier) can become
            # stale and misroute to the Excel agent. Let in-graph classification
            # re-evaluate using the augmented message.
            pre_classified_for_graph = pre_classified_intent
            if rag_augmented_query != query:
                pre_classified_for_graph = None

            raw_out = await chat_graph.ainvoke(
                {
                    "messages": input_messages,
                    "project_id": project_id_uuid,
                    "user_id": user_key,
                    "allowed_db_uri": project_db_url,
                    "pre_classified_intent": pre_classified_for_graph,
                },
                config=cfg,
            )
            out = dict(raw_out) if isinstance(raw_out, dict) else {}

            response_text = str(out.get("response", ""))
            original_response_text = response_text
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

            logger.info(
                "UseCase: Query processed, session_id=%s, agent=%s, success=%s",
                current_session_id,
                agent_id,
                success,
            )

            # Persist the new turn.
            if share_ctx is not None:
                # Forked share session: JSONB snapshot from the owner is the
                # authoritative history. The LangGraph checkpoint here may not
                # reflect that snapshot, so do NOT overwrite JSONB with the
                # graph state — that would wipe the snapshot. Append the new
                # turn manually instead.
                if agent.session_manager and (original_user_query or "").strip():
                    await agent.session_manager.add_message("user", original_user_query)
                if agent.session_manager and (response_text or "").strip():
                    await agent.session_manager.add_message("assistant", response_text)
            elif agent.session_manager and isinstance(out.get("messages"), list):
                # Owner sessions: sync the full transcript from the graph
                # checkpoint (existing behaviour).
                rows = langchain_messages_to_session_rows(out["messages"])
                if (
                    rows
                    and response_text != original_response_text
                    and rows[-1].get("role") == "assistant"
                ):
                    rows[-1] = {**rows[-1], "content": response_text}
                # Strip upload markers from the persisted user row so the chat
                # history doesn't show internal ``[UPLOADED_EXCEL_*]`` blocks
                # on reload. We rewrite only the most recent user row (the
                # turn we just added); older rows are already clean.
                if original_user_query is not None:
                    for i in range(len(rows) - 1, -1, -1):
                        if rows[i].get("role") == "user":
                            rows[i] = {**rows[i], "content": original_user_query}
                            break
                await agent.session_manager.replace_messages_from_graph_export(rows)

            tool_events = out.get("tool_events") or []
            if not isinstance(tool_events, list):
                tool_events = []

            result = {
                "response": response_text,
                "agent_id": agent_id,
                "session_id": current_session_id,
                "requires_approval": pending_workflow_resume,
                "intent": out.get("intent") or {},
                "tool_events": tool_events,
                "pending_workflow_resume": pending_workflow_resume,
                "workflow_state": workflow_state,
            }

            # Persist pending approval payload for SQL gate (CREATE TABLE / mutation preview).
            await self._persist_pending_approval_from_workflow(
                agent,
                current_session_id,
                pending_workflow_resume=pending_workflow_resume,
                workflow_state=(workflow_state if isinstance(workflow_state, dict) else None),
                tool_events=tool_events,
            )

            return response_text, current_session_id, tool_events, pending_workflow_resume, warnings, success
        except Exception as e:
            logger.error(f"UseCase: Error processing query: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}") from e

    async def mint_superset_guest_token(
        self,
        user_key: str,
        embedded_uuid: str,
        project_id: str,
        ttl_seconds: int = 300,
        chart_id: Optional[int] = None,
    ) -> dict:
        """Verify project ownership, then mint a Superset Guest Token via MCP.

        Trust model:
        - Caller (frontend) supplies (embedded_uuid, project_id).
        - We verify ``user_key`` actually owns ``project_id`` via ProjectRepository.
        - We do NOT independently verify that ``embedded_uuid`` belongs to that
          project — embedded_uuids are treated as semi-secret and only delivered
          through authenticated chat replies.

        Auto-recreate: when a chart was created in a previous Superset session
        and the metadata DB has since been reset, the original wrapper dashboard
        is gone. If ``chart_id`` is provided and the chart still exists, we
        re-wrap it to obtain a new ``embedded_uuid`` and re-mint. The returned
        ``embedded_uuid`` may therefore differ from the requested one — the
        frontend must update its iframe accordingly.
        """
        if not embedded_uuid or not embedded_uuid.strip():
            raise HTTPException(status_code=400, detail="embedded_uuid is required")
        if not project_id or not project_id.strip():
            raise HTTPException(status_code=400, detail="project_id is required")

        try:
            uuid.UUID(project_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid project_id")

        if not self._project_repo:
            raise HTTPException(status_code=500, detail="Project repository unavailable")

        project = await self._project_repo.get_project_by_id(project_id, user_key)
        if not project and self._share_repo:
            # Forked-share recipients don't own the project. If they have an
            # active share for it, look the project up under the owner instead
            # so charts in shared chats render for the recipient too.
            owner_sub = await self._share_repo.get_owner_for_recipient_project(
                recipient_google_sub=user_key, project_id=project_id
            )
            if owner_sub:
                project = await self._project_repo.get_project_by_id(project_id, owner_sub)
        if not project:
            raise HTTPException(status_code=403, detail="Project not accessible")

        ttl = int(ttl_seconds or 300)
        cache_key = (user_key, embedded_uuid)
        now = time.time()
        cached = self._guest_token_cache.get(cache_key)
        if cached and cached[0] > now + self._guest_token_cache_safety_seconds:
            return cached[1]

        agent = await self._agent_repo.get_agent(user_key=user_key)
        result = await agent.mint_superset_guest_token(
            embedded_uuid=embedded_uuid,
            project_id=project_id,
            user_id=user_key,
            ttl_seconds=ttl,
        )

        if (not isinstance(result, dict) or result.get("error")) and chart_id:
            try:
                rewrap = await agent.rewrap_chart_for_embed(
                    chart_id=int(chart_id),
                    project_id=project_id,
                )
            except Exception as e:
                rewrap = {"error": f"rewrap failed: {e}"}
            new_uuid = (rewrap or {}).get("embedded_uuid")
            if new_uuid and new_uuid != embedded_uuid:
                result = await agent.mint_superset_guest_token(
                    embedded_uuid=new_uuid,
                    project_id=project_id,
                    user_id=user_key,
                    ttl_seconds=int(ttl_seconds or 300),
                )
                if isinstance(result, dict) and not result.get("error"):
                    result["embedded_uuid"] = new_uuid

        if not isinstance(result, dict) or result.get("error"):
            # Combine error + message so the caller sees the actual upstream
            # cause (e.g. "404 Not Found: Embedded dashboard <uuid> missing"),
            # not just the generic header that wraps it.
            err = (result or {}).get("error") or "Failed to mint guest token"
            extra = (result or {}).get("message") or (result or {}).get("details")
            msg = f"{err}: {extra}" if extra and extra != err else str(err)
            logger.warning(
                "[mint_guest_token] failed: %s | embedded_uuid=%s project_id=%s chart_id=%s",
                msg, embedded_uuid, project_id, chart_id,
            )
            raise HTTPException(status_code=502, detail=msg)

        token = result.get("token")
        if not token:
            raise HTTPException(status_code=502, detail="Guest token missing in response")

        response = {
            "token": token,
            "embed_url": result.get("embed_url") or "",
            "superset_domain": result.get("supersetDomain") or result.get("superset_domain"),
            "embedded_uuid": result.get("embedded_uuid") or embedded_uuid,
            "ttl_seconds": int(result.get("ttl_seconds") or ttl_seconds or 300),
        }
        # Cache under both the original and (if rewrapped) the new uuid so
        # subsequent requests with either key dedupe to the same token.
        expires_at = now + response["ttl_seconds"]
        self._guest_token_cache[(user_key, embedded_uuid)] = (expires_at, response)
        if response["embedded_uuid"] != embedded_uuid:
            self._guest_token_cache[(user_key, response["embedded_uuid"])] = (expires_at, response)
        return response

    async def chat_stream(
        self,
        user_key: str,
        message: str,
        session_id: str | None,
        project_id: str | None = None,
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
            try:
                response_text, sid, tool_events, pending, warnings, success = await self.chat(
                    user_key, message, session_id, project_id
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
        lang: str = "en",
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
                result = await agent.approve_and_execute(session_id=current_session_id, approved=True)

                # Approval preview state is stored in SessionManager (persisted).
                # If the server reloaded or state is missing, fallback to executing the SQL
                # that the frontend already extracted from the preview message.
                approve_result_text = str(result.get("response", "")) if isinstance(result, dict) else str(result)
                approve_missing_state = approve_result_text.strip().startswith("Session ") and " not found" in approve_result_text
                approve_no_sql = (approve_result_text.strip() == "No SQL to execute")
                if approve_missing_state or approve_no_sql:
                    logger.warning(
                        "UseCase: approval path unusable (%s), falling back to direct execute_sql. session_id=%s",
                        "no session" if approve_missing_state else "no pending sql",
                        current_session_id,
                    )
                    result = await agent.execute_sql(query, lang=lang)
            else:
                # Legacy: call execute_sql directly
                result = await agent.execute_sql(query, lang=lang)
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

