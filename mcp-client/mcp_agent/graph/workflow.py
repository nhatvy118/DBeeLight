"""LangGraph workflow builder - passes BaseAgent to workflows for tool execution."""

import logging
from typing import Optional, Dict, Any
from openai import OpenAI

from mcp_agent.graph.database_workflow import DatabaseAgentWorkflow
from mcp_agent.graph.excel_workflow import ExcelAgentWorkflow
from mcp_agent.graph.graph_state import AgentState
from mcp_agent.graph.state import StageType

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """Main workflow class that routes to agent-specific workflows.

    Each workflow delegates to BaseAgent for tool execution.
    """

    def __init__(
        self,
        llm: Optional[OpenAI] = None,
        model: str = "gpt-4o-mini",
        agents: Dict[str, Any] = None,
    ):
        self.llm = llm or OpenAI()
        self.model = model

        # Initialize agent-specific workflows with BaseAgent instances
        self.workflows: Dict[str, Any] = {}

        if agents:
            self._init_workflows(agents)

    def _init_workflows(self, agents: Dict[str, Any]):
        """Initialize workflows with BaseAgent instances."""
        self.workflows = {
            "database": DatabaseAgentWorkflow(llm=self.llm, agent=agents.get("database")),
            "excel": ExcelAgentWorkflow(llm=self.llm, agent=agents.get("excel")),
        }

    async def run(
        self,
        session_id: str,
        user_message: str,
        agent_type: str,
    ) -> AgentState:
        """Run workflow for specific agent type.

        Args:
            session_id: Unique session identifier
            user_message: User's input message
            agent_type: Which agent to use ("database", "excel", etc.)

        Returns:
            Final state after workflow completes
        """
        workflow = self.workflows.get(agent_type)
        if not workflow:
            logger.error(f"[Workflow] Unknown agent type: {agent_type}")
            return {
                "session_id": session_id,
                "current_stage": "ERROR",
                "agent_type": agent_type,
                "user_message": user_message,
                "error": f"Unknown agent type: {agent_type}",
                "output": {"error": f"Unknown agent type: {agent_type}"}
            }

        logger.info(f"[Workflow] Running {agent_type} workflow for session {session_id}")
        result = await workflow.run(session_id, user_message)
        logger.info(f"[Workflow] Completed with stage: {result.get('current_stage')}")

        return result

    async def continue_from_stage(
        self,
        session_id: str,
        current_stage: str,
        agent_type: str,
        context: Dict[str, Any],
        message: str = None,
    ) -> AgentState:
        """Continue workflow from a specific stage.

        Used for resuming after user approval or other interruptions.
        """
        workflow = self.workflows.get(agent_type)
        if not workflow:
            return {"error": f"Unknown agent type: {agent_type}"}

        # Handle approval at SQL_PREVIEW stage
        if current_stage == StageType.SQL_PREVIEW.value and context.get("approved"):
            # User approved - continue to execution
            context["wait_user"] = False

        return await self.run(session_id, message or context.get("user_message", ""), agent_type)
