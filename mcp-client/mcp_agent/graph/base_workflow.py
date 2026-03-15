"""Base workflow class for agents - delegates to BaseAgent for tool execution."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from langgraph.graph import StateGraph, END

from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import StageType, AgentWorkflowConfig


class BaseAgentWorkflow(ABC):
    """Base class for agent-specific workflows.

    Each agent should extend this and define its own stages.
    Nodes delegate to BaseAgent for tool execution.
    """

    # Subclasses must define their workflow config
    workflow_config: AgentWorkflowConfig = None

    def __init__(self, llm: Any = None, agent: Any = None):
        self.llm = llm
        self.agent = agent  # BaseAgent instance for tool execution

    @abstractmethod
    def get_stage_handlers(self) -> Dict[str, Callable]:
        """Return dict of stage_name -> handler function.

        Each handler receives (state: AgentState, agent: BaseAgent) and returns updated state.
        """
        pass

    def _build_graph(self) -> StateGraph:
        """Build LangGraph from workflow config."""
        workflow = StateGraph(AgentState)

        handlers = self.get_stage_handlers()

        # Add all stages as nodes
        for stage in self.workflow_config.stages:
            stage_name = stage.value
            if stage_name in handlers:
                # Create wrapper that passes agent to handler
                handler = handlers[stage_name]
                async def node_wrapper(state, _agent=self.agent, _handler=handler):
                    return await _handler(state, _agent)
                workflow.add_node(stage_name, node_wrapper)
            else:
                # Fallback node that just passes through
                async def pass_through(state):
                    return state
                workflow.add_node(stage_name, pass_through)

        # Add START node
        async def start_handler(state):
            first_stage = self.workflow_config.stages[0].value if self.workflow_config.stages else "INTENT_PARSE"
            return {**state, "current_stage": first_stage}

        workflow.add_node("START", start_handler)
        workflow.add_node("ERROR", self._error_handler)

        # Set entry point
        workflow.set_entry_point("START")

        # Add edges based on config
        if self.workflow_config.stages:
            workflow.add_edge("START", self.workflow_config.stages[0].value)

            for stage in self.workflow_config.stages:
                stage_name = stage.value
                next_stage = self.workflow_config.transitions.get(stage_name)

                if next_stage:
                    # Check if this stage waits for user
                    if stage_name in self.workflow_config.wait_stages:
                        # Conditional edge - wait or proceed
                        workflow.add_conditional_edges(
                            stage_name,
                            self._should_wait,
                            {
                                "wait": stage_name,  # Stay at same stage
                                "proceed": next_stage,
                            }
                        )
                    else:
                        workflow.add_edge(stage_name, next_stage)

        # All stages lead to DONE
        if StageType.DONE.value not in self.workflow_config.transitions.values():
            workflow.add_edge(StageType.DONE.value, END)
        else:
            workflow.add_edge(StageType.DONE.value, END)

        workflow.add_edge("ERROR", END)

        return workflow.compile()

    def _should_wait(self, state: AgentState) -> str:
        """Determine if we should wait for user or proceed."""
        if state.get("wait_user"):
            return "wait"
        return "proceed"

    async def _error_handler(self, state: AgentState) -> AgentState:
        """Error handler."""
        return {
            **state,
            "current_stage": "ERROR",
            "output": {"error": state.get("error", "Unknown error")}
        }

    async def run(self, session_id: str, user_message: str) -> AgentState:
        """Run the workflow."""
        state = create_initial_state(session_id, user_message, self.workflow_config.agent_id)
        graph = self._build_graph()
        result = await graph.ainvoke(state)
        return result
