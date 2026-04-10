"""Orchestrator — routes all queries through LangGraph workflow."""

import logging
import uuid
import asyncio
from typing import Any, Dict, List, Optional, TypedDict

from openai import OpenAI
from langgraph.graph import END, StateGraph

from mcp_agent.agents.base_agent import BaseAgent
from mcp_agent.session.session_manager import SessionManager
from mcp_agent.orchestration.intent_service import IntentService

logger = logging.getLogger(__name__)


class OrchestratorState(TypedDict, total=False):
    session_id: str
    user_message: str
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
        mapped = {"db": "database", "database": "database", "excel": "excel", "superset": "superset"}
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
        query = str(state.get("user_message") or "").strip()
        intent_result = await self._intent_service.classify(query, list(self._agents.keys()))
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
        if route == "superset":
            return "superset"
        if route in ("db_readonly", "db_create_table", "db_mutation", "database"):
            return "db"
        primary = str(state.get("primary_agent") or "database").lower().strip()
        if primary == "superset":
            return "superset"
        if primary == "excel":
            return "excel"
        workflow_id = intent_result.get("workflow_id")
        if workflow_id:
            if str(workflow_id).startswith("db_"):
                return "db"
            if str(workflow_id).startswith("excel"):
                return "excel"
            if str(workflow_id).startswith("superset"):
                return "superset"
        return "db"

    async def _clarify_node(self, state: OrchestratorState) -> OrchestratorState:
        """Return a follow-up question to disambiguate intent before routing."""
        intent_result = state.get("intent_result") or {}
        q = str(intent_result.get("clarification_question") or "").strip()
        if not q:
            q = "Bạn có thể nói rõ yêu cầu của bạn hơn được không?"
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
        message = str(intent_result.get("nl_query") or state.get("user_message") or "")
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
        message = str(intent_result.get("nl_query") or state.get("user_message") or "")
        database_route = self._database_route_from_intent(intent_result)
        self._session_agent_map[session_id] = "database"
        try:
            workflow_state = await self.workflow.run(
                session_id=session_id,
                user_message=message,
                agent_type="database",
                thread_id=session_id,
                database_route=database_route,
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

    async def _superset_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        return await self._run_agent_node(state, "superset")

    async def _excel_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        return await self._run_agent_node(state, "excel")

    async def _hybrid_agent_node(self, state: OrchestratorState) -> OrchestratorState:
        session_id = str(state.get("session_id") or "")
        intent_result = state.get("intent_result") or {}
        message = str(intent_result.get("nl_query") or state.get("user_message") or "")
        chart_type = str(intent_result.get("chart_type") or "").strip().lower()
        requires_export = bool(intent_result.get("requires_export"))
        file_format = str(intent_result.get("file_format") or "").strip().lower()

        # Fan-out selection: DB is base; add Superset for charting; add Excel for exports/files.
        selected_agents: List[str] = ["database"]
        if chart_type:
            selected_agents.append("superset")
        if requires_export or file_format in {"xlsx", "xls", "csv"}:
            selected_agents.append("excel")

        selected_agents = [a for a in dict.fromkeys(selected_agents) if a in self._agents]
        if not selected_agents:
            selected_agents = ["database"] if "database" in self._agents else list(self._agents.keys())[:1]

        tasks = [
            self._run_subgraph_for_agent(session_id=session_id, message=message, agent_type=agent_type)
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
                if stage in ("SCHEMA_HITL", "SQL_PREVIEW"):
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
        pending = current_stage in ("SCHEMA_HITL", "SQL_PREVIEW")
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
        graph.add_node("SUPERSET_AGENT", self._superset_agent_node)
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
                "superset": "SUPERSET_AGENT",
                "excel": "EXCEL_AGENT",
                "hybrid": "HYBRID_AGENT",
            },
        )
        graph.add_edge("CLARIFY", "AGGREGATE_RESPONSE")
        graph.add_edge("DB_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("SUPERSET_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("EXCEL_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("HYBRID_AGENT", "AGGREGATE_RESPONSE")
        graph.add_edge("AGGREGATE_RESPONSE", END)
        return graph.compile()

    async def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process query through top-level LangGraph orchestrator."""
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(f"[Orchestrator] Processing query for session {session_id}")
        try:
            graph_state = await self.orchestrator_graph.ainvoke(
                {"session_id": session_id, "user_message": query}
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

        if output_type == "chart_embed":
            events.append({
                "tool": "create_chart",
                "type": "chart_embed",
                "payload": output.get("embed_url"),
            })

        return events

    async def approve_and_execute(
        self,
        session_id: str,
        approved: bool = True,
    ) -> Dict[str, Any]:
        """Resume workflow after user approval via LangGraph Command(resume=).

        The workflow was paused at SQL_PREVIEW or SCHEMA_HITL via interrupt().
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
        pending_workflow_resume = current_stage in ("SCHEMA_HITL", "SQL_PREVIEW")

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

    async def connect_project_to_superset(
        self,
        project_id: str,
        db_url: str,
        project_name: str = "",
    ) -> str:
        """Register a project's database in Superset via SupersetAgent."""
        superset_agent = self._agents.get("superset")
        if not superset_agent:
            return "No Superset agent available"

        db_name = project_name or f"project_{project_id}"

        sqlalchemy_uri = db_url
        if db_url.startswith("/") or db_url.startswith("."):
            import os
            abs_path = os.path.abspath(db_url)
            sqlalchemy_uri = f"sqlite:///{abs_path}"
            logger.info(f"[Orchestrator] Converted SQLite path to: {sqlalchemy_uri}")

        for server_name, session in superset_agent.sessions.items():
            try:
                result = await session.call_tool("register_database", {
                    "name": db_name,
                    "sqlalchemy_uri": sqlalchemy_uri,
                })
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[Orchestrator] register_database result: {result_content}")
                return result_content
            except Exception as e:
                logger.debug(f"[Orchestrator] register_database not found in {server_name}: {e}")
                continue

        return "register_database tool not found in any Superset session"
