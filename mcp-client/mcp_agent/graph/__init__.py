"""LangGraph workflow module for per-agent workflows.

Each agent has its own workflow with different stages.
"""

from mcp_agent.graph.state import (
    SessionStatus,
    StageType,
    AgentWorkflowConfig,
    DATABASE_WORKFLOW,
    EXCEL_WORKFLOW,
    AGENT_WORKFLOWS,
    AgentContext,
    StageResult,
)
from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.base_workflow import BaseAgentWorkflow
from mcp_agent.graph.database_workflow import DatabaseAgentWorkflow
from mcp_agent.graph.excel_workflow import ExcelAgentWorkflow
from mcp_agent.graph.workflow import AgentWorkflow

# Workflow registry
WORKFLOWS = {
    "database": DatabaseAgentWorkflow,
    "excel": ExcelAgentWorkflow,
}


def get_workflow(agent_type: str):
    """Get workflow class for an agent type."""
    return WORKFLOWS.get(agent_type)


__all__ = [
    # State types
    "SessionStatus",
    "StageType",
    "AgentWorkflowConfig",
    "AgentContext",
    "StageResult",
    # Workflow configs
    "DATABASE_WORKFLOW",
    "EXCEL_WORKFLOW",
    "AGENT_WORKFLOWS",
    # Graph state
    "AgentState",
    "create_initial_state",
    # Base classes
    "BaseAgentWorkflow",
    # Concrete workflows
    "DatabaseAgentWorkflow",
    "ExcelAgentWorkflow",
    # Main workflow class
    "AgentWorkflow",
    # Registry
    "WORKFLOWS",
    "get_workflow",
]
