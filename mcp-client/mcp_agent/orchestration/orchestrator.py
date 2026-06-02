"""Orchestrator — routes all queries through LangGraph workflow."""

import logging
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from openai import OpenAI
from langgraph.graph import END, StateGraph

from mcp_agent.agents.base_agent import BaseAgent
from mcp_agent.session.session_manager import SessionManager
from mcp_agent.orchestration.intent_service import IntentService
from mcp_agent.progress import emit as _progress_emit

logger = logging.getLogger(__name__)


class OrchestratorState(TypedDict, total=False):
    session_id: str
    user_message: str
    conversation_context: List[Dict[str, Any]]
    conversation_summary: str
    intent_result: Dict[str, Any]
    primary_agent: str
    agent_id: str
    workflow_state: Dict[str, Any]
    success: bool
    response: str
    error: Optional[str]
    pending_workflow_resume: bool
    # Project / user scoping — propagated to sub-workflows for tool-level enforcement
    project_id: Optional[str]
    user_id: Optional[str]
    allowed_db_uri: Optional[str]
    # When user picks a specific file from the DataSource selector, its SQLite table name
    # is injected here so intent classification uses it as an authoritative table_hint.
    active_file_table_hint: Optional[str]


class Orchestrator:
    """LangGraph orchestrator with parse-intent + route + agent wrappers."""

    def __init__(
        self,
        agents: List[BaseAgent],
        session_manager: SessionManager,
        router_model: str = "gpt-5.2",
    ):
        if not agents:
            raise ValueError("At least one agent is required")

        self._agents: Dict[str, BaseAgent] = {a.agent_id: a for a in agents}
        self.session_manager = session_manager
        self._router_model = router_model

        # Shared OpenAI client for all LLM calls
        self._openai = OpenAI()

        # Intent service for initial agent selection (before entering graph)
        self._intent_service = IntentService(model=router_model, llm=self._openai)

        # Agent subgraph workflow runner
        self._workflow = None
        self._orchestrator_graph = None

        # Track agent type per session (for approve_and_execute resume)
        self._session_agent_map: Dict[str, str] = {}

        # Outer chat graph (MessagesState + checkpoint_ns=chat); built lazily.
        self._chat_compiled_graph = None

        logger.info(f"[Orchestrator] Initialized with agents: {list(self._agents.keys())}")

    @property
    def sessions(self) -> Dict[str, Any]:
        """Expose sessions from the first agent."""
        first = next(iter(self._agents.values()))
        return first.sessions

    @property
    def workflow(self):
        """Lazy load AgentWorkflow that executes per-agent subgraphs."""
        if self._workflow is None:
            from mcp_agent.graph import AgentWorkflow
            self._workflow = AgentWorkflow(
                llm=self._openai,
                model=self._router_model,
                agents=self._agents,
            )
        return self._workflow

    @property
    def orchestrator_graph(self):
        """Lazy load top-level orchestration graph."""
        if self._orchestrator_graph is None:
            self._orchestrator_graph = self._build_orchestrator_graph()
        return self._orchestrator_graph

    def _agent_key_to_type(self, key: str) -> str:
        mapped = {"db": "database", "database": "database", "excel": "excel", "chart": "chart"}
        return mapped.get((key or "").lower().strip(), "database")

    def _database_route_from_intent(self, intent_result: Dict[str, Any]) -> str:
        """Map flat ``intent_result['route']`` to AgentWorkflow ``database_route``."""
        route = intent_result.get("route")
        if route == "db_readonly":
            return "readonly"
        if route == "db_create_table":
            return "create_table"
        if route == "db_mutation":
            return "mutation"
        if route == "db_general":
            return "general"
        return "general"

    async def _parse_intent_node(self, state: OrchestratorState) -> OrchestratorState:
        query = str(state.get("user_message") or "").strip()
        conversation_context = state.get("conversation_context") or []
        conversation_summary = str(state.get("conversation_summary") or "").strip()
        await _progress_emit("classify", "running", "Analyzing request...")
        intent_result = await self._intent_service.classify(
            query,
            list(self._agents.keys()),
            conversation_context=conversation_context,
            conversation_summary=conversation_summary,
        )
        ir = intent_result.to_dict()
        # If user explicitly selected a file as the active data source, its SQLite table
        # name takes precedence over whatever the LLM inferred as table_hint.
        forced_hint = str(state.get("active_file_table_hint") or "").strip()
        if forced_hint:
            ir["table_hint"] = forced_hint
            logger.info("[Orchestrator] active_file_table_hint overrides table_hint → %s", forced_hint)
        primary_agent = intent_result.agent_type or intent_result.fallback_agent or "database"
        return {
            **state,
            "intent_result": ir,
            "primary_agent": primary_agent,
        }

    def _route_node(self, state: OrchestratorState) -> str:
        intent_result = state.get("intent_result") or {}
        if bool(intent_result.get("needs_clarification")):
            return "clarify"
        route = str(intent_result.get("route") or "").strip()
        if route == "excel":
            return "excel"
        if route == "chart":
            return "chart"
        if route in ("db_readonly", "db_create_table", "db_mutation", "db_general"):
            return "db"
        primary = str(state.get("primary_agent") or "database").lower().strip()
        if primary == "chart":
            return "chart"
        if primary == "excel":
            return "excel"
        workflow_id = intent_result.get("workflow_id")
        if workflow_id:
            if str(workflow_id).startswith("db_"):
                return "db"
            if str(workflow_id).startswith("excel"):
                return "excel"
            if str(workflow_id).startswith("chart"):
                return "chart"
        return "db"

    async def _clarify_node(self, state: OrchestratorState) -> OrchestratorState:
        """Return a follow-up question to disambiguate intent before routing."""
        intent_result = state.get("intent_result") or {}
        q = str(intent_result.get("clarification_question") or "").strip()
        if not q:
            q = "Could you clarify your request?"
        return {
            **state,
            "agent_id": "orchestrator",
            "workflow_state": {
                "current_stage": "CLARIFY",
                "output": {"type": "clarification", "message": q},
            },
        }

    async def _run_agent_node(self, state: OrchestratorState, agent_key: str) -> OrchestratorState:
        session_id = str(state.get("session_id") or "")
        intent_result = state.get("intent_result") or {}
        # Prefer raw ``user_message`` so markers (e.g. ``[UPLOADED_EXCEL_PATH_*]``,
        # RAG blocks) reach Excel/Chart. ``nl_query`` is normalized and drops them.
        message = str(state.get("user_message") or intent_result.get("nl_query") or "")
        agent_type = self._agent_key_to_type(agent_key)
        self._session_agent_map[session_id] = agent_type
        await _progress_emit("agent", "running", f"Routing to {agent_type} agent...")
        try:
            workflow_state = await self.workflow.run(
                session_id=session_id,
                user_message=message,
                agent_type=agent_type,
                thread_id=session_id,
            )
        except Exception as e:
            logger.exception("[Orchestrator] %s agent wrapper error: %s", agent_type, e)
            return {
                **state,
                "agent_id": agent_type,
                "workflow_state": {},
                "error": f"{agent_type} workflow error: {e}",
            }
        return {
            **state,
            "agent_id": agent_type,
            "workflow_state": workflow_state,
        }

    async def _db_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        """Run database path: three workflows from intent, else DatabaseAgent."""
        session_id = str(state.get("session_id") or "")
        intent_result = state.get("intent_result") or {}
        # Keep the full augmented user message (including [ATTACHED FILES CONTEXT])
        # for DB workflows. ``nl_query`` is normalized and may drop RAG table hints.
        message = str(state.get("user_message") or intent_result.get("nl_query") or "")
        database_route = self._database_route_from_intent(intent_result)
        self._session_agent_map[session_id] = "database"
        try:
            workflow_state = await self.workflow.run(
                session_id=session_id,
                user_message=message,
                agent_type="database",
                thread_id=session_id,
                database_route=database_route,
                orchestrator_intent=intent_result,
            )
        except Exception as e:
            logger.exception("[Orchestrator] database workflow error: %s", e)
            return {
                **state,
                "agent_id": "database",
                "workflow_state": {},
                "error": f"database workflow error: {e}",
            }
        return {
            **state,
            "agent_id": "database",
            "workflow_state": workflow_state,
        }

    async def _chart_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        return await self._run_agent_node(state, "chart")

    async def _excel_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        return await self._run_agent_node(state, "excel")

    async def _aggregate_response_node(self, state: OrchestratorState) -> OrchestratorState:
        workflow_state = state.get("workflow_state") or {}
        if not workflow_state:
            return {
                **state,
                "response": str(state.get("error") or "No workflow state produced."),
                "pending_workflow_resume": False,
            }

        output = workflow_state.get("output", {})
        if isinstance(output, dict):
            response = output.get("message") or output.get("data") or str(output)
        else:
            response = str(output)

        current_stage = str(workflow_state.get("current_stage") or "")
        pending = current_stage in ("SCHEMA_PREVIEW", "SQL_PREVIEW")
        return {
            **state,
            "response": str(response),
            "pending_workflow_resume": pending,
        }

    def _build_orchestrator_graph(self):
        graph = StateGraph(OrchestratorState)
        graph.add_node("PARSE_INTENT", self._parse_intent_node)
        graph.add_node("CLARIFY", self._clarify_node)
        graph.add_node("DB_AGENT", self._db_agent_node)
        graph.add_node("CHART_AGENT", self._chart_agent_node)
        graph.add_node("EXCEL_AGENT", self._excel_agent_node)
        graph.add_node("AGGREGATE_RESPONSE", self._aggregate_response_node)
        graph.set_entry_point("PARSE_INTENT")
        graph.add_conditional_edges(
            "PARSE_INTENT",
            self._route_node,
            {
                "clarify": "CLARIFY",
                "db": "DB_AGENT",
                "chart": "CHART_AGENT",
                "excel": "EXCEL_AGENT",
            },
        )
        graph.add_edge("CLARIFY", "AGGREGATE_RESPONSE")
        graph.add_edge("DB_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("CHART_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("EXCEL_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("AGGREGATE_RESPONSE", END)
        return graph.compile()

    async def classify_intent(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        conversation_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Classify a user query without running the full orchestration graph.

        Used by callers (e.g. share-permission gating in chat_usecase) that
        need the routing decision *before* deciding whether to invoke the
        agent at all. Returns the same dict shape as ``IntentResult.to_dict()``
        — notably the ``route`` field (one of: db_readonly, db_create_table,
        db_mutation, db_general, excel, chart).
        """
        intent_result = await self._intent_service.classify(
            query,
            list(self._agents.keys()),
            conversation_context=conversation_context or [],
            conversation_summary=conversation_summary or "",
        )
        return intent_result.to_dict()

    async def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        conversation_summary: Optional[str] = None,
        *,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        allowed_db_uri: Optional[str] = None,
        active_file_table_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process query through top-level LangGraph orchestrator."""
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(f"[Orchestrator] Processing query for session {session_id}")
        try:
            graph_state = await self.orchestrator_graph.ainvoke(
                {
                    "session_id": session_id,
                    "user_message": query,
                    "conversation_context": conversation_context or [],
                    "conversation_summary": str(conversation_summary or "").strip(),
                    "project_id": project_id,
                    "user_id": user_id,
                    "allowed_db_uri": allowed_db_uri,
                    "active_file_table_hint": active_file_table_hint or None,
                }
            )
        except Exception as e:
            logger.exception("[Orchestrator] Orchestration graph error: %s", e)
            return {
                "response": f"Workflow error: {e}",
                "agent_id": "unknown",
                "session_id": session_id,
                "requires_approval": False,
                "intent": {},
                "tool_events": [],
                "pending_workflow_resume": False,
                "workflow_state": {},
            }

        intent = graph_state.get("intent_result", {}) if isinstance(graph_state, dict) else {}
        agent_id = str((graph_state or {}).get("agent_id") or self._agent_key_to_type(str(intent.get("agent_type") or "database")))
        workflow_state = (graph_state or {}).get("workflow_state") or {}
        response = str((graph_state or {}).get("response") or "")
        pending_workflow_resume = bool((graph_state or {}).get("pending_workflow_resume"))
        success = bool((graph_state or {}).get("success", True))
        tool_events = self._extract_tool_events_from_state(workflow_state)

        return {
            "response": response,
            "agent_id": agent_id,
            "session_id": session_id,
            "requires_approval": pending_workflow_resume,
            "intent": intent,
            "tool_events": tool_events,
            "pending_workflow_resume": pending_workflow_resume,
            "workflow_state": {
                **workflow_state,
                "success": success,
            },
        }

    def _extract_tool_events_from_state(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract structured tool events from workflow state for frontend rendering."""
        events: List[Dict[str, Any]] = []
        output = state.get("output", {})

        if not isinstance(output, dict):
            return events

        output_type = output.get("type", "")

        if output_type == "schema_preview":
            events.append({
                "tool": "show_create_table_schema",
                "type": "schema_preview",
                "payload": output.get("message", ""),
            })

        if output_type == "sql_preview":
            events.append({
                "tool": "execute_query",
                "type": "sql_preview",
                "payload": {
                    "sql": state.get("sql"),
                    "mutation_preview_markdown": output.get("mutation_preview_markdown"),
                },
            })

        if output_type == "execution_complete":
            events.append({
                "tool": "execute_query",
                "type": "sql_execution",
                "payload": {
                    "sql": output.get("sql"),
                    "result": output.get("result"),
                },
            })

        return events

    async def approve_and_execute(
        self,
        session_id: str,
        approved: bool = True,
        *,
        sql: str | None = None,
    ) -> Dict[str, Any]:
        """Resume workflow after user approval via LangGraph Command(resume=).

        The workflow was paused at SQL_PREVIEW or SCHEMA_PREVIEW via interrupt().
        We resume it with the approval decision.
        """
        logger.info(f"[Orchestrator] Resuming workflow for session {session_id}, approved={approved}")

        try:
            workflow_state = await self.workflow.run(
                session_id=session_id,
                user_message="",
                agent_type=self._get_agent_type_for_session(session_id),
                resume=approved,
                thread_id=session_id,
            )
            logger.info(
                "[Orchestrator] Resume workflow_state keys=%s, stage=%s, output_type=%s",
                (list(workflow_state.keys()) if isinstance(workflow_state, dict) else []),
                (workflow_state.get("current_stage") if isinstance(workflow_state, dict) else None),
                (
                    (workflow_state.get("output") or {}).get("type")
                    if isinstance(workflow_state, dict) and isinstance(workflow_state.get("output"), dict)
                    else None
                ),
            )
        except Exception as e:
            logger.exception(f"[Orchestrator] Workflow resume error: {e}")
            return {
                "response": f"Resume error: {e}",
                "tool_events": [],
                "pending_workflow_resume": False,
                "workflow_state": {},
            }

        output = workflow_state.get("output", {})
        output_type = output.get("type", "") if isinstance(output, dict) else ""
        if isinstance(output, dict):
            response = output.get("message", str(output))
        else:
            response = str(output)

        current_stage = workflow_state.get("current_stage", "")
        pending_workflow_resume = current_stage in ("SCHEMA_PREVIEW", "SCHEMA_APPROVAL", "SQL_PREVIEW")

        # Workflow already ended at DONE with preview only (e.g. stale error routing) — run SQL directly.
        if approved and output_type == "sql_preview" and not pending_workflow_resume:
            sql_to_run = (sql or workflow_state.get("sql") or "").strip()
            if sql_to_run:
                logger.warning(
                    "[Orchestrator] Resume returned sql_preview at stage=%s; executing SQL directly",
                    current_stage,
                )
                return await self.execute_sql(sql_to_run)

        return {
            "response": response,
            "tool_events": self._extract_tool_events_from_state(workflow_state),
            "pending_workflow_resume": pending_workflow_resume,
            "workflow_state": workflow_state,
        }

    def _get_agent_type_for_session(self, session_id: str) -> str:
        """Get agent type for a session from the map, default to database."""
        return self._session_agent_map.get(session_id, "database")

    async def resume_workflow(
        self,
        session_id: str,
        approved: bool = True,
    ) -> Dict[str, Any]:
        """Alias for approve_and_execute. Resume LangGraph workflow after user decision."""
        return await self.approve_and_execute(session_id=session_id, approved=approved)

    async def execute_sql(self, sql: str) -> Dict[str, Any]:
        """Execute SQL directly (bypasses LangGraph workflow). Used for fallback."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return {"response": "No database agent available", "tool_events": []}

        for _server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("execute_query", {"query": sql})
                result_content = result.content
                if hasattr(result_content, "text"):
                    result_text = str(result_content.text)
                elif isinstance(result_content, list) and result_content:
                    first = result_content[0]
                    result_text = str(first.text) if hasattr(first, "text") else str(result_content)
                else:
                    result_text = str(result_content)

                return {
                    "response": result_text,
                    "tool_events": [{
                        "tool": "execute_query",
                        "type": "sql_execution",
                        "payload": {"sql": sql, "result": result_text},
                    }],
                }
            except Exception:
                continue

        return {"response": "Failed to execute query", "tool_events": []}

    async def get_chat_graph(self):
        """Compiled chat graph: ingest → summarize → orchestrate (checkpoint-isolated)."""
        if self._chat_compiled_graph is None:
            from mcp_agent.graph.chat_graph import build_chat_graph
            from mcp_agent.graph.langgraph_checkpointer import get_async_checkpointer

            cp = await get_async_checkpointer()
            self._chat_compiled_graph = build_chat_graph(self, cp)
        return self._chat_compiled_graph

    async def merge_resume_into_chat_checkpoint(
        self,
        session_id: str,
        user_visible_message: Optional[str],
        assistant_text: str,
    ) -> None:
        """Append resume turn to chat checkpoint so history stays aligned with SessionManager."""
        from langchain_core.messages import AIMessage, HumanMessage

        from mcp_agent.graph.chat_graph import CHAT_CHECKPOINT_NS

        u = (user_visible_message or "").strip()
        a = (assistant_text or "").strip()
        if not u and not a:
            return

        graph = await self.get_chat_graph()
        # NOTE: On current LangGraph runtime, aupdate_state may treat checkpoint_ns as
        # subgraph path and raise "Subgraph chat not found". Use thread-only config.
        cfg = {"configurable": {"thread_id": session_id}}
        msgs = []
        if u:
            msgs.append(HumanMessage(content=u))
        if a:
            msgs.append(AIMessage(content=a))
        await graph.aupdate_state(cfg, {"messages": msgs})

    async def cleanup(self) -> None:
        """Clean up all agents."""
        for agent in self._agents.values():
            await agent.cleanup()

    async def connect_external_db(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> str:
        """Connect the database agent to an external PostgreSQL database via UI."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool(
                    "connect_db",
                    {
                        "host": host,
                        "port": port,
                        "database": database,
                        "username": username,
                        "password": password,
                    },
                )
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] connect_external_db result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] connect_db not found in {server_name}: {e}")
                continue

        return "connect_db tool not found in any session"

    async def check_db_connection(self) -> str:
        """Ping the database agent to check if it has an active connection."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("list_tables", {})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                # If list_tables succeeds → connected
                if "not connected" in result_content.lower():
                    return result_content
                return "connected"
            except Exception as e:
                logger.debug(f"[Orchestrator] check_db_connection error in {server_name}: {e}")
                continue

        return "Database not connected"

    async def disconnect_external_db(self) -> str:
        """Disconnect the database agent from its current external database."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("disconnect_db", {})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] disconnect_external_db result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] disconnect_db not found in {server_name}: {e}")
                continue

        return "disconnect_db tool not found in any session"

    async def connect_to_project_db(self, db_url: str) -> str:
        """Connect the database agent to a project's SQLite database (sets primary adapter)."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("connect_sqlite", {"file_path": db_url})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] connect_sqlite result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] connect_sqlite not found in {server_name}: {e}")
                continue

        return "connect_sqlite tool not found in any session"

    async def connect_session_file_db(self, db_url: str, allowed_tables: Optional[str] = None) -> str:
        """Connect a session-file SQLite as the *session* adapter WITHOUT overriding the primary DB.

        Use this when the user has selected both their primary database and an uploaded
        file — the primary adapter stays intact and both can be queried simultaneously.

        Args:
            db_url: Path / URL of the session SQLite file.
            allowed_tables: Comma-separated list of table names to expose from this file.
                When provided, ``list_tables`` on the session adapter will only show these
                tables so the LLM cannot accidentally reference tables from other uploads.
        """
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        tool_args: dict = {"file_path": db_url}
        if allowed_tables:
            tool_args["allowed_tables"] = allowed_tables

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("connect_session_sqlite", tool_args)
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] connect_session_sqlite result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] connect_session_sqlite not found in {server_name}: {e}")
                continue

        return "connect_session_sqlite tool not found in any session"

    async def disconnect_session_file_db(self) -> str:
        """Disconnect the session-file SQLite adapter so subsequent queries only see the primary DB."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("disconnect_session_sqlite", {})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] disconnect_session_sqlite result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] disconnect_session_sqlite not found in {server_name}: {e}")
                continue

        return "disconnect_session_sqlite tool not found in any session"

    async def connect_chart_to_project_db(self, db_url: str) -> str:
        """Set the active database connection on the chart-server for this user's
        ChartAgent. Called per chat turn from the api-server, after it has
        validated that the requesting user owns the project the db_url belongs to.

        ``db_url`` is forwarded as-is to the chart-server's ``chart_connect_db``
        tool, which validates the scheme and (for SQLite) that the path lies
        under ``CHART_SQLITE_ALLOWED_DIRS`` as defense in depth.
        """
        chart_agent = self._agents.get("chart")
        if not chart_agent:
            return "No chart agent available"

        for server_name, session in chart_agent.sessions.items():
            try:
                result = await session.call_tool("chart_connect_db", {"db_url": db_url})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] chart_connect_db result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] chart_connect_db not found in {server_name}: {e}")
                continue

        return "chart_connect_db tool not found in any chart-server session"
