"""Hybrid Orchestrator - combines LLM-driven and LangGraph approaches.

Best practice:
1. Use IntentRouter to classify query first
2. Simple queries → LLM-driven (BaseAgent.process_query)
3. Complex queries → LangGraph workflow (with BaseAgent for tool execution)
4. Conversational → Handle as follow-up
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Literal

from openai import OpenAI

from mcp_agent.base_agent import BaseAgent
from mcp_agent.session import SessionManager
from mcp_agent.intent_router import IntentRouter, QueryComplexity

logger = logging.getLogger(__name__)


class HybridOrchestrator:
    """Hybrid orchestrator that routes to appropriate handler based on query type.

    Flow:
    1. IntentRouter classifies query (simple vs complex vs conversational)
    2. Simple → LLM-driven (BaseAgent.process_query)
    3. Complex → LangGraph workflow (with BaseAgent for tool execution)
    4. Conversational → Continue conversation
    """

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
        self._openai = OpenAI()
        self._router_model = router_model

        # Intent router for classification
        self._intent_router = IntentRouter(llm=self._openai, model=router_model)

        # LangGraph workflow (for complex queries) - pass agents for tool execution
        self._workflow = None  # Lazy load
        self._workflow_agents = self._agents

        # Session states
        self._session_states: Dict[str, Dict] = {}

        logger.info(f"[HybridOrchestrator] Initialized with agents: {list(self._agents.keys())}")

    @property
    def sessions(self) -> Dict[str, Any]:
        """Expose sessions from the first agent."""
        first = next(iter(self._agents.values()))
        return first.sessions

    @property
    def workflow(self):
        """Lazy load LangGraph workflow with agents."""
        if self._workflow is None:
            from mcp_agent.graph import AgentWorkflow
            self._workflow = AgentWorkflow(
                llm=self._openai,
                model=self._router_model,
                agents=self._workflow_agents,
            )
        return self._workflow

    async def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """Process user query using hybrid approach.

        Returns:
            {
                "response": str,
                "agent_id": str,
                "session_id": str,
                "approach": "llm_driven" | "workflow" | "conversational",
                "intent": dict
            }
        """
        # Create session if not exists
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(f"[HybridOrchestrator] Processing query for session {session_id}")

        # Step 1: Route to appropriate agent first
        agent_id = await self._route_to_agent(query)
        agent = self._agents.get(agent_id)

        if not agent:
            return {
                "response": f"No agent found for type: {agent_id}",
                "agent_id": agent_id,
                "session_id": session_id,
                "approach": "error",
                "intent": {}
            }

        # Step 2: Classify query to determine handling approach
        classification = await self._intent_router.classify(query, agent_id)
        complexity = classification.get("complexity", "simple")

        logger.info(f"[HybridOrchestrator] Classification: intent={classification.get('intent')}, complexity={complexity}")

        # Step 3: Route to appropriate handler
        if complexity == QueryComplexity.CONVERSATIONAL:
            response = await self._handle_conversational(query, agent, session_id, verbose)
            handler = "conversational"

        elif complexity == QueryComplexity.COMPLEX or classification.get("requires_workflow"):
            response = await self._handle_workflow(query, agent_id, session_id, classification)
            handler = "workflow"

        else:
            # Simple - use LLM-driven (BaseAgent)
            response = await self._handle_llm_driven(query, agent, session_id, verbose)
            handler = "llm_driven"

        return {
            "response": response,
            "agent_id": agent_id,
            "session_id": session_id,
            "approach": handler,
            "intent": classification,
        }

    async def _route_to_agent(self, query: str) -> str:
        """Route query to database or excel agent."""
        if len(self._agents) == 1:
            return next(iter(self._agents.keys()))

        response = self._openai.chat.completions.create(
            model=self._router_model,
            messages=[
                {
                    "role": "system",
                    "content": """Route to:
- "database" for SQL, tables, data queries, exports to database
- "excel" for Excel files, charts, data import/export

Reply with ONLY agent id."""
                },
                {"role": "user", "content": query}
            ],
            temperature=0,
        )

        choice = response.choices[0]
        agent_id = choice.message.content.strip().lower() if choice.message else ""
        return agent_id if agent_id in self._agents else next(iter(self._agents.keys()))

    async def _handle_llm_driven(
        self,
        query: str,
        agent: BaseAgent,
        session_id: str,
        verbose: bool,
    ) -> str:
        """Handle simple query using LLM-driven approach (BaseAgent)."""
        logger.info(f"[HybridOrchestrator] Using LLM-driven approach")

        response = await agent.process_query(query, verbose=verbose)
        return response

    async def _handle_workflow(
        self,
        query: str,
        agent_id: str,
        session_id: str,
        classification: Dict,
    ) -> str:
        """Handle complex query using LangGraph workflow (with BaseAgent)."""
        logger.info(f"[HybridOrchestrator] Using LangGraph workflow for {agent_id}")

        requires_approval = classification.get("requires_approval", False)

        if requires_approval:
            # Generate SQL first, then ask for approval
            return await self._handle_with_approval(query, agent_id, session_id, classification)
        else:
            # Run full workflow with BaseAgent
            return await self._run_workflow(query, agent_id, session_id)

    async def _handle_with_approval(
        self,
        query: str,
        agent_id: str,
        session_id: str,
        classification: Dict,
    ) -> str:
        """Handle query that requires user approval."""
        logger.info(f"[HybridOrchestrator] Handling with approval flow")

        # Get agent
        agent = self._agents.get(agent_id)
        if not agent:
            return "Agent not found"

        # Generate SQL using BaseAgent
        response = await agent.process_query(
            f"Generate SQL for: {query}. Show the SQL but do NOT execute it.",
            verbose=False
        )

        # Store SQL in session for later execution
        self._session_states[session_id] = {
            "sql": response,
            "agent_id": agent_id,
            "intent": classification,
        }

        return f"""Please review the SQL:

```sql
{response}
```

Click **Execute** to run this SQL, or **Cancel** to abort."""

    async def _run_workflow(
        self,
        query: str,
        agent_id: str,
        session_id: str,
    ) -> str:
        """Run LangGraph workflow for complex queries."""
        logger.info(f"[HybridOrchestrator] Running workflow for {agent_id}")

        # Run workflow - it will use BaseAgent internally for tool execution
        result = await self.workflow.run(session_id, query, agent_id)

        # Extract response from result
        output = result.get("output", {})
        response = output.get("message", str(output))

        return response

    async def _handle_conversational(
        self,
        query: str,
        agent: BaseAgent,
        session_id: str,
        verbose: bool,
    ) -> str:
        """Handle conversational/follow-up queries."""
        logger.info(f"[HybridOrchestrator] Handling as conversational")

        response = await agent.process_query(query, verbose=verbose)
        return response

    async def execute_sql(
        self,
        sql: str,
        lang: str = "en",
    ) -> str:
        """Execute SQL after user approval."""
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        for server_name, session in db_agent.sessions.items():
            try:
                result = await session.call_tool("execute_query", {"query": sql})
                result_content = result.content

                try:
                    if hasattr(result_content, "text"):
                        result_text = str(result_content.text)
                    elif isinstance(result_content, list) and result_content:
                        first = result_content[0]
                        if hasattr(first, "text"):
                            result_text = str(first.text)
                        else:
                            result_text = str(result_content)
                    else:
                        result_text = str(result_content)
                except Exception:
                    result_text = str(result_content)

                return self._translate_message(result_text, lang)
            except Exception:
                continue

        return "Failed to execute query"

    async def approve_and_execute(
        self,
        session_id: str,
        approved: bool = True,
    ) -> str:
        """Execute SQL after user approval."""
        state = self._session_states.get(session_id)

        if not state:
            return f"Session {session_id} not found"

        if not approved:
            self._session_states.pop(session_id, None)
            return "SQL execution cancelled."

        sql = state.get("sql")
        if not sql:
            return "No SQL to execute"

        result = await self.execute_sql(sql)
        self._session_states.pop(session_id, None)

        return result

    def _translate_message(self, text: str, lang: str) -> str:
        """Translate message."""
        if lang != "vi":
            return text

        try:
            response = self._openai.chat.completions.create(
                model=self._router_model,
                messages=[
                    {"role": "system", "content": "Translate to Vietnamese. Keep formatting."},
                    {"role": "user", "content": text}
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
        """
        Connect the database agent to a project's SQLite database.

        Args:
            db_url: Path to the SQLite database file (e.g., "path/to/project.db")

        Returns:
            Result message from the connection attempt.
        """
        # Find database agent
        db_agent = self._agents.get("database")
        if not db_agent:
            return "No database agent available"

        # Find connect_sqlite tool in agent's sessions
        for server_name, session in db_agent.sessions.items():
            try:
                # Call connect_sqlite tool
                result = await session.call_tool("connect_sqlite", {"file_path": db_url})
                result_content = result.content
                if not isinstance(result_content, str):
                    result_content = str(result_content)
                logger.info(f"[HybridOrchestrator] connect_sqlite result: {result_content}")
                return result_content
            except Exception as e:
                # Tool not found in this server, continue
                logger.debug(f"[HybridOrchestrator] connect_sqlite not found in {server_name}: {e}")
                continue

        return "connect_sqlite tool not found in any session"
