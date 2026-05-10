"""Orchestrator — routes all queries through LangGraph workflow."""

import logging
import uuid
import asyncio
from typing import Any, Dict, List, Optional, TypedDict

from openai import OpenAI
from langgraph.graph import END, StateGraph

from mcp_agent.agents.base_agent import BaseAgent
from mcp_agent.session.session_manager import SessionManager
from mcp_agent.orchestration.intent_service import IntentService, detect_user_lang

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
    hybrid_results: Dict[str, Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    success: bool
    response: str
    error: Optional[str]
    pending_workflow_resume: bool
    # Project / user scoping — propagated to sub-workflows for tool-level enforcement
    project_id: Optional[str]
    user_id: Optional[str]
    allowed_db_uri: Optional[str]
    # Pre-classified intent (from caller). When present, _parse_intent_node
    # skips its own LLM classification and reuses this dict.
    pre_classified_intent: Optional[Dict[str, Any]]


class Orchestrator:
    """LangGraph orchestrator with parse-intent + route + agent wrappers."""

    def __init__(
        self,
        agents: List[BaseAgent],
        session_manager: SessionManager,
        router_model: str = "gpt-4o-mini",
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
        return "general"

    async def _parse_intent_node(self, state: OrchestratorState) -> OrchestratorState:
        # Reuse caller-provided classification when present (chat_usecase passes
        # one for share permission gating). Skips a duplicate LLM call.
        pre = state.get("pre_classified_intent")
        if isinstance(pre, dict) and pre.get("route"):
            primary_agent = (
                pre.get("agent_type") or pre.get("fallback_agent") or "database"
            )
            return {**state, "intent_result": pre, "primary_agent": primary_agent}

        query = str(state.get("user_message") or "").strip()
        conversation_context = state.get("conversation_context") or []
        conversation_summary = str(state.get("conversation_summary") or "").strip()
        intent_result = await self._intent_service.classify(
            query,
            list(self._agents.keys()),
            conversation_context=conversation_context,
            conversation_summary=conversation_summary,
        )
        ir = intent_result.to_dict()
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
        if route in ("db_readonly", "db_create_table", "db_mutation", "database"):
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
            lang = str(intent_result.get("detected_language") or "").lower() \
                or detect_user_lang(str(state.get("user_message") or ""))
            q = (
                "Bạn có thể nói rõ yêu cầu của bạn hơn được không?"
                if lang == "vi"
                else "Could you clarify your request?"
            )
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

    async def _run_subgraph_for_agent(
        self,
        session_id: str,
        message: str,
        agent_type: str,
    ) -> Dict[str, Any]:
        self._session_agent_map[session_id] = agent_type
        try:
            return await self.workflow.run(
                session_id=session_id,
                user_message=message,
                agent_type=agent_type,
                thread_id=session_id,
            )
        except Exception as e:
            logger.exception("[Orchestrator] %s hybrid subgraph error: %s", agent_type, e)
            return {
                "current_stage": "ERROR",
                "output": {"type": "error", "message": f"{agent_type} workflow error: {e}"},
                "error": str(e),
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

    async def _hybrid_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        session_id = str(state.get("session_id") or "")
        intent_result = state.get("intent_result") or {}
        raw_message = str(state.get("user_message") or "")
        normalized_message = str(intent_result.get("nl_query") or raw_message)
        chart_type = str(intent_result.get("chart_type") or "").strip().lower()
        requires_export = bool(intent_result.get("requires_export"))
        file_format = str(intent_result.get("file_format") or "").strip().lower()

        # Fan-out selection: DB is base; add Chart for visualization; add Excel for exports/files.
        selected_agents: List[str] = ["database"]
        if chart_type:
            selected_agents.append("chart")
        if requires_export or file_format in {"xlsx", "xls", "csv"}:
            selected_agents.append("excel")

        selected_agents = [a for a in dict.fromkeys(selected_agents) if a in self._agents]
        if not selected_agents:
            selected_agents = ["database"] if "database" in self._agents else list(self._agents.keys())[:1]

        tasks = [
            self._run_subgraph_for_agent(
                session_id=session_id,
                # DB + Excel need full message (RAG / upload path markers). Chart uses NL.
                message=(
                    raw_message
                    if agent_type in ("database", "excel")
                    else normalized_message
                ),
                agent_type=agent_type,
            )
            for agent_type in selected_agents
        ]
        results = await asyncio.gather(*tasks)
        hybrid_results = {agent_type: result for agent_type, result in zip(selected_agents, results)}
        warnings: List[Dict[str, Any]] = []
        success_count = 0
        failed_agents: List[str] = []
        for agent_type, wf_state in hybrid_results.items():
            stage = str((wf_state or {}).get("current_stage") or "")
            output = (wf_state or {}).get("output", {})
            err = str((wf_state or {}).get("error") or "")
            output_type = output.get("type", "") if isinstance(output, dict) else ""
            is_error = stage == "ERROR" or output_type == "error" or bool(err)
            if is_error:
                failed_agents.append(agent_type)
                warnings.append(
                    {
                        "type": "agent_failed",
                        "agent": agent_type,
                        "message": str(output.get("message") if isinstance(output, dict) else err) or f"{agent_type} failed",
                    }
                )
            else:
                success_count += 1

        # Hybrid policy: at least 2 successful agent paths.
        policy_ok = success_count >= 2
        if not policy_ok:
            warnings.append(
                {
                    "type": "hybrid_policy_violation",
                    "message": (
                        "Hybrid result requires at least 2 successful agents. "
                        f"Only {success_count} succeeded out of {len(selected_agents)}."
                    ),
                    "success_count": success_count,
                    "selected_agents": selected_agents,
                    "failed_agents": failed_agents,
                }
            )

        return {
            **state,
            "agent_id": "hybrid",
            "hybrid_results": hybrid_results,
            "warnings": warnings,
            "success": policy_ok,
        }

    async def _aggregate_response_node(self, state: OrchestratorState) -> OrchestratorState:
        hybrid_results = state.get("hybrid_results") or {}
        if isinstance(hybrid_results, dict) and hybrid_results:
            parts: List[str] = []
            pending = False
            warnings = state.get("warnings") or []
            for agent_type, wf_state in hybrid_results.items():
                output = wf_state.get("output", {}) if isinstance(wf_state, dict) else {}
                if isinstance(output, dict):
                    msg = output.get("message") or output.get("data") or str(output)
                else:
                    msg = str(output)
                stage = str((wf_state or {}).get("current_stage") or "")
                if stage in ("SCHEMA_PREVIEW", "SQL_PREVIEW"):
                    pending = True
                label = agent_type.upper()
                parts.append(f"[{label}]\n{str(msg).strip()}")

            warning_text = ""
            if warnings:
                warning_lines = []
                for w in warnings:
                    if isinstance(w, dict):
                        warning_lines.append(f"- {str(w.get('message') or w)}")
                warning_text = "\n\n[WARNINGS]\n" + "\n".join(warning_lines) if warning_lines else ""

            return {
                **state,
                "response": ("\n\n".join(parts).strip() + warning_text).strip(),
                "pending_workflow_resume": pending,
            }

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
        graph.add_node("HYBRID_AGENT", self._hybrid_agent_node)
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
                "hybrid": "HYBRID_AGENT",
            },
        )
        graph.add_edge("CLARIFY", "AGGREGATE_RESPONSE")
        graph.add_edge("DB_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("CHART_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("EXCEL_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("HYBRID_AGENT", "AGGREGATE_RESPONSE")
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
        db_mutation, database, excel, chart).
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
        pre_classified_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process query through top-level LangGraph orchestrator.

        ``project_id`` / ``user_id`` / ``allowed_db_uri`` flow down to per-agent workflows
        so chart-server (and future agents) can enforce that resources are scoped to the project.

        ``pre_classified_intent`` (optional): an ``IntentResult.to_dict()`` payload from
        a caller that already ran intent classification (e.g. chat_usecase's share
        permission gate). When present, skips the duplicate classify call in
        ``_parse_intent_node``.
        """
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
                    "pre_classified_intent": pre_classified_intent,
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
        hybrid_results = (graph_state or {}).get("hybrid_results") or {}
        response = str((graph_state or {}).get("response") or "")
        pending_workflow_resume = bool((graph_state or {}).get("pending_workflow_resume"))
        warnings = (graph_state or {}).get("warnings") or []
        success = bool((graph_state or {}).get("success", True))
        tool_events = self._extract_tool_events_from_state(workflow_state)
        if isinstance(hybrid_results, dict) and hybrid_results:
            tool_events = []
            for wf_state in hybrid_results.values():
                if isinstance(wf_state, dict):
                    tool_events.extend(self._extract_tool_events_from_state(wf_state))
            # Structured warning events for UI consumers
            for w in warnings:
                if isinstance(w, dict):
                    tool_events.append(
                        {
                            "tool": "orchestrator",
                            "type": "warning",
                            "payload": w,
                        }
                    )

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
                "hybrid_results": hybrid_results,
                "warnings": warnings,
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
        if isinstance(output, dict):
            response = output.get("message", str(output))
        else:
            response = str(output)

        current_stage = workflow_state.get("current_stage", "")
        pending_workflow_resume = current_stage in ("SCHEMA_PREVIEW", "SCHEMA_APPROVAL", "SQL_PREVIEW")

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

    async def execute_sql(self, sql: str, lang: str = "en") -> Dict[str, Any]:
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

                translated = self._translate_message(result_text, lang)
                return {
                    "response": translated,
                    "tool_events": [{
                        "tool": "execute_query",
                        "type": "sql_execution",
                        "payload": {"sql": sql, "result": result_text},
                    }],
                }
            except Exception:
                continue

        return {"response": "Failed to execute query", "tool_events": []}

    def _translate_message(self, text: str, lang: str) -> str:
        """Translate message to target language."""
        if lang != "vi":
            return text
        try:
            client = OpenAI()
            response = client.chat.completions.create(
                model=self._router_model,
                messages=[
                    {"role": "system", "content": "Translate to Vietnamese. Keep formatting."},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
            )
            translated = response.choices[0].message.content
            if translated:
                return translated
        except Exception:
            pass
        return text

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

    async def connect_to_project_db(self, db_url: str) -> str:
        """Connect the database agent to a project's SQLite database."""
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
