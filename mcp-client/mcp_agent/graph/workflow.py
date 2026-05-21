"""LangGraph workflow router - dispatches to correct workflow based on operation type."""

import json
import logging
from typing import Optional, Dict, Any, Literal, cast
from openai import OpenAI

from mcp_agent.graph.readonly_workflow import ReadOnlyWorkflow
from mcp_agent.graph.create_table_workflow import CreateTableWorkflow
from mcp_agent.graph.mutation_workflow import MutationWorkflow
from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import StageType

logger = logging.getLogger(__name__)

# Safe DB operations that route to ReadOnlyWorkflow (direct tool execution)
_SAFE_DB_OPERATIONS = frozenset(
    {"LIST_TABLES", "DESCRIBE_TABLE"}
)


DatabaseRoute = Optional[Literal["readonly", "create_table", "mutation", "general"]]


class AgentWorkflow:
    """Per-agent LangGraph runner.

    Database paths (usually chosen by Orchestrator via ``database_route``):
    - ``readonly`` → ReadOnlyWorkflow (SELECT, list/describe tables, …)
    - ``create_table`` → CreateTableWorkflow
    - ``mutation`` → MutationWorkflow
    - ``general`` → DatabaseAgent.process_query (tool loop; request is DB-related but not one of the three graphs)

    If ``database_route`` is omitted (``None``), operation is classified locally for backward compatibility.

    Non-database: excel / chart agents (both pure tool loops, no LangGraph).
    """

    def __init__(
        self,
        llm: Optional[OpenAI] = None,
        model: str = "gpt-4o-mini",
        agents: Dict[str, Any] = None,
    ):
        self.llm = llm or OpenAI()
        self.model = model

        self.workflows: Dict[str, Any] = {}
        self._session_workflow_map: Dict[str, str] = {}
        self._database_agent: Any = None
        # Excel and Chart agents have no LangGraph workflow — their tool loops
        # handle the request directly. We hold references for ``_run_non_database``.
        self._excel_agent: Any = None
        self._chart_agent: Any = None
        if agents:
            self._init_workflows(agents)

    def _init_workflows(self, agents: Dict[str, Any]):
        """Initialize all workflows with agent instances."""
        self._database_agent = agents.get("database")
        self._excel_agent = agents.get("excel")
        self._chart_agent = agents.get("chart")
        self.workflows = {
            "readonly": ReadOnlyWorkflow(llm=self.llm, agent=agents.get("database")),
            "create_table": CreateTableWorkflow(llm=self.llm, agent=agents.get("database")),
            "mutation": MutationWorkflow(llm=self.llm, agent=agents.get("database")),
        }

    def _classify_operation(self, user_message: str) -> str:
        """Classify the operation type from user message using LLM."""
        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Analyze the database request and return the operation type as JSON. "
                            "Operations: SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, EXPORT, "
                            "LIST_TABLES, DESCRIBE_TABLE, UNKNOWN. "
                            "Return JSON with key 'operation'."
                        ),
                    },
                    {"role": "user", "content": user_message}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content or "{}")
            return str(result.get("operation", "SELECT")).strip().upper()
        except Exception:
            return "SELECT"

    async def run(
        self,
        session_id: str,
        user_message: str,
        agent_type: str,
        *,
        resume=None,
        thread_id: Optional[str] = None,
        database_route: DatabaseRoute = None,
        orchestrator_intent: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        """Run workflow for specific agent type, routing to correct sub-workflow for database."""
        if agent_type != "database":
            return await self._run_non_database(
                session_id,
                user_message,
                agent_type,
                resume,
                thread_id,
            )

        # For database, use orchestrator route or classify locally
        return await self._run_database(
            session_id,
            user_message,
            resume,
            thread_id,
            database_route,
            orchestrator_intent,
        )

    async def _run_database(
        self,
        session_id: str,
        user_message: str,
        resume=None,
        thread_id: Optional[str] = None,
        database_route: DatabaseRoute = None,
        orchestrator_intent: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        """Route database request: explicit ``database_route`` from Orchestrator, else local classify.

        When resuming (user approved/rejected), skip routing and use the workflow that was interrupted.
        """
        # On resume, go directly to the workflow that was interrupted
        if resume is not None:
            wf_name = self._session_workflow_map.get(session_id, "mutation")
            workflow = cast(Any, self.workflows.get(wf_name, self.workflows["mutation"]))
            logger.info(f"[Workflow] Resume detected, using workflow: {wf_name}")
            return await workflow.run(
                session_id, user_message, resume=resume, thread_id=thread_id
            )

        if database_route == "general":
            self._session_workflow_map.pop(session_id, None)
            logger.info("[Workflow] database_route=general → DatabaseAgent.process_query")
            return await self._run_database_base_agent(session_id, user_message)

        if database_route == "readonly":
            self._session_workflow_map[session_id] = "readonly"
            logger.info("[Workflow] database_route=readonly → ReadOnlyWorkflow")
            return await self.workflows["readonly"].run(
                session_id,
                user_message,
                orchestrator_intent=orchestrator_intent,
            )

        if database_route == "create_table":
            workflow = cast(Any, self.workflows["create_table"])
            self._session_workflow_map[session_id] = "create_table"
            logger.info("[Workflow] database_route=create_table → CreateTableWorkflow")
            return await workflow.run(
                session_id, user_message, resume=resume, thread_id=thread_id
            )

        if database_route == "mutation":
            workflow = cast(Any, self.workflows["mutation"])
            self._session_workflow_map[session_id] = "mutation"
            logger.info("[Workflow] database_route=mutation → MutationWorkflow")
            return await workflow.run(
                session_id, user_message, resume=resume, thread_id=thread_id
            )

        # No orchestrator route — local classify (legacy / direct callers)
        operation = self._classify_operation(user_message)
        logger.info(f"[Workflow] Database operation classified as: {operation}")

        if operation in _SAFE_DB_OPERATIONS or operation == "SELECT":
            workflow = self.workflows["readonly"]
            self._session_workflow_map[session_id] = "readonly"
            return await workflow.run(
                session_id,
                user_message,
                orchestrator_intent=orchestrator_intent,
            )

        if operation == "CREATE":
            workflow = cast(Any, self.workflows["create_table"])
            self._session_workflow_map[session_id] = "create_table"
            return await workflow.run(
                session_id, user_message, resume=resume, thread_id=thread_id
            )

        if operation == "UNKNOWN":
            self._session_workflow_map.pop(session_id, None)
            logger.info("[Workflow] UNKNOWN → BaseAgent.process_query (tool loop)")
            return await self._run_database_base_agent(session_id, user_message)

        # INSERT, UPDATE, DELETE, ALTER, DROP, EXPORT
        workflow = cast(Any, self.workflows["mutation"])
        self._session_workflow_map[session_id] = "mutation"
        return await workflow.run(
            session_id, user_message, resume=resume, thread_id=thread_id
        )

    async def _run_database_base_agent(
        self,
        session_id: str,
        user_message: str,
    ) -> AgentState:
        """Full DatabaseAgent tool loop (orchestrator ``database_route=general``, or UNKNOWN classify)."""
        agent = self._database_agent
        if not agent:
            base = create_initial_state(session_id, user_message, "database")
            return {
                **base,
                "current_stage": StageType.ERROR.value,
                "error": "No database agent available",
                "output": {
                    "type": "error",
                    "message": "No database agent available for conversational mode.",
                },
            }
        try:
            text = await agent.process_query(user_message, verbose=False, persist_history=True)
        except Exception as e:
            logger.exception("[Workflow] BaseAgent.process_query failed: %s", e)
            base = create_initial_state(session_id, user_message, "database")
            return {
                **base,
                "current_stage": StageType.ERROR.value,
                "error": str(e),
                "output": {"type": "error", "message": f"Agent error: {e}"},
            }
        base = create_initial_state(session_id, user_message, "database")
        return {
            **base,
            "current_stage": StageType.DONE.value,
            "output": {
                "type": "agent_response",
                "message": text,
            },
        }

    async def _run_non_database(
        self,
        session_id: str,
        user_message: str,
        agent_type: str,
        resume=None,
        thread_id: Optional[str] = None,
        *,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        allowed_db_uri: Optional[str] = None,
    ) -> AgentState:
        """Run non-database agents (excel, chart) via their tool loops.

        Neither has a LangGraph workflow — chart-server's active DB connection
        is set by the orchestrator (``connect_chart_to_project_db``) before this
        is reached, so the agent only needs to introspect schema and emit the
        appropriate ``generate_*_chart`` call.
        """
        agent_map = {"excel": self._excel_agent, "chart": self._chart_agent}
        agent = agent_map.get(agent_type)
        if agent is None:
            logger.error(f"[Workflow] Unknown agent type: {agent_type}")
            return {
                "session_id": session_id,
                "current_stage": StageType.ERROR.value,
                "agent_type": agent_type,
                "user_message": user_message,
                "error": f"Unknown agent type: {agent_type}",
                "output": {"error": f"Unknown agent type: {agent_type}"},
            }
        if resume is not None or thread_id is not None:
            logger.warning("[Workflow] resume/thread_id ignored for agent_type=%s", agent_type)
        logger.info(f"[Workflow] Delegating {agent_type} to agent tool loop for session {session_id}")
        try:
            response = await agent.process_query(user_message, verbose=False)
        except Exception as e:
            logger.exception("[Workflow] %s agent error: %s", agent_type, e)
            return {
                "session_id": session_id,
                "current_stage": StageType.ERROR.value,
                "agent_type": agent_type,
                "user_message": user_message,
                "error": f"{agent_type} agent error: {e}",
                "output": {"error": f"{agent_type} agent error: {e}"},
            }
        return {
            "session_id": session_id,
            "current_stage": StageType.DONE.value,
            "agent_type": agent_type,
            "user_message": user_message,
            "output": {"type": "agent_response", "message": response},
        }
