"""LangGraph workflow module for per-agent workflows.

Each agent has its own workflow with different stages.
"""

from mcp_agent.graph.state import (
    SessionStatus,
    StageType,
    AgentWorkflowConfig,
    DATABASE_WORKFLOW,
    AGENT_WORKFLOWS,
    AgentContext,
    StageResult,
)
from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.database_utils import (
    strip_sql_fences,
    is_execute_query_error_response,
    format_mutation_preview_markdown,
    markdown_table_from_rows,
    build_insert_values_markdown,
    insert_values_preview_markdown,
)
from mcp_agent.graph.readonly_workflow import ReadOnlyWorkflow
from mcp_agent.graph.create_table_workflow import CreateTableWorkflow
from mcp_agent.graph.mutation_workflow import MutationWorkflow
from mcp_agent.graph.workflow import AgentWorkflow

# Workflow registry — ``excel`` and ``chart`` are intentionally absent:
# their agent tool loops handle every request; there's no LangGraph workflow.
WORKFLOWS = {
    "database": None,  # Replaced by database sub-workflows
    "readonly": ReadOnlyWorkflow,
    "create_table": CreateTableWorkflow,
    "mutation": MutationWorkflow,
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
    "AGENT_WORKFLOWS",
    # Graph state
    "AgentState",
    "create_initial_state",
    # Database utilities
    "strip_sql_fences",
    "is_execute_query_error_response",
    "format_mutation_preview_markdown",
    "markdown_table_from_rows",
    "build_insert_values_markdown",
    "insert_values_preview_markdown",
    # Concrete workflows
    "ReadOnlyWorkflow",
    "CreateTableWorkflow",
    "MutationWorkflow",
    # Main workflow class
    "AgentWorkflow",
    # Registry
    "WORKFLOWS",
    "get_workflow",
]
