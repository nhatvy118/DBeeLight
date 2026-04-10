"""Excel agent workflow with LangGraph - each workflow defines its own stages."""

import logging
import json
from typing import Dict, Any
from openai import OpenAI
from langgraph.graph import StateGraph, END

from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import (
    StageType,
    EXCEL_WORKFLOW,
)

logger = logging.getLogger(__name__)


class ExcelAgentWorkflow:
    """Workflow for Excel agent - each stage defined independently."""

    workflow_config = EXCEL_WORKFLOW

    def __init__(self, llm=None, agent=None):
        self.llm = llm or OpenAI()
        self.agent = agent

    def get_stage_handlers(self) -> Dict[str, callable]:
        return {
            StageType.INTENT_PARSE.value: self.intent_parse,
            StageType.FILE_LOAD.value: self.file_load,
            StageType.DATA_ANALYZE.value: self.data_analyze,
            StageType.DATA_TRANSFORM.value: self.data_transform,
            StageType.CHART_GENERATE.value: self.chart_generate,
            StageType.EXPORT.value: self.export,
        }

    def _build_graph(self) -> Any:
        """Build LangGraph from workflow config."""
        workflow = StateGraph(AgentState)
        handlers = self.get_stage_handlers()
        cfg = self.workflow_config

        for stage in cfg.stages:
            stage_name = stage.value
            if stage_name in handlers:
                handler = handlers[stage_name]
                async def node_wrapper(state, _agent=self.agent, _handler=handler):
                    return await _handler(state, _agent)
                workflow.add_node(stage_name, node_wrapper)
            else:
                async def pass_through(state):
                    return state
                workflow.add_node(stage_name, pass_through)

        async def start_handler(state):
            first = cfg.stages[0].value if cfg.stages else StageType.INTENT_PARSE.value
            return {**state, "current_stage": first}

        workflow.add_node("START", start_handler)

        async def done_handler(state):
            return {**state, "current_stage": StageType.DONE.value}

        workflow.add_node(StageType.DONE.value, done_handler)

        workflow.set_entry_point("START")
        workflow.add_edge("START", cfg.stages[0].value)

        for stage in cfg.stages:
            stage_name = stage.value
            next_stage = cfg.transitions.get(stage_name)
            if next_stage:
                workflow.add_edge(stage_name, next_stage)

        workflow.add_edge(StageType.DONE.value, END)

        return workflow.compile()

    async def run(self, session_id: str, user_message: str) -> AgentState:
        """Run the workflow."""
        state = create_initial_state(session_id, user_message, self.workflow_config.agent_id)
        graph = self._build_graph()
        result = await graph.ainvoke(state)
        return result

    async def intent_parse(self, state: AgentState, agent) -> AgentState:
        """Parse user intent for Excel operations."""
        user_message = state["user_message"]
        logger.info(f"[Excel] Intent parse: {user_message[:50]}...")

        response = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Analyze the Excel request and extract:
                    - operation: import, export, chart, analyze, transform
                    - file_path: path to Excel file (if mentioned)
                    - sheet_name: sheet name (if mentioned)
                    - columns: columns mentioned
                    - target_table: database table name (for import/export)
                    - detected_language: en or vi

                    Return JSON."""
                },
                {"role": "user", "content": user_message}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        try:
            intent = json.loads(response.choices[0].message.content)
        except:
            intent = {
                "operation": "analyze",
                "file_path": None,
                "sheet_name": None,
                "columns": [],
                "target_table": None,
                "detected_language": "en"
            }

        return {
            **state,
            "intent": intent,
            "detected_language": intent.get("detected_language", "en"),
            "file_path": intent.get("file_path"),
            "sheet_name": intent.get("sheet_name"),
        }

    async def file_load(self, state: AgentState, agent) -> AgentState:
        """Load Excel file using agent."""
        file_path = state.get("file_path")
        intent = state.get("intent", {})
        logger.info(f"[Excel] File load: {file_path}")

        if not agent:
            return {**state, "output": {"message": "No agent available"}}

        # Delegate to BaseAgent
        if file_path:
            response = await agent.process_query(
                f"Import the Excel file at: {file_path}",
                verbose=False
            )
            logger.info(f"[Excel] File load response: {response[:200]}...")

        return {
            **state,
            "output": {
                "type": "file_loaded",
                "file_path": file_path,
                "message": f"File {file_path} loaded successfully"
            }
        }

    async def data_analyze(self, state: AgentState, agent) -> AgentState:
        """Analyze data using agent."""
        intent = state.get("intent", {})
        operation = intent.get("operation", "analyze")
        logger.info(f"[Excel] Data analyze: {operation}")

        if not agent:
            return {**state, "output": {"message": "No agent available"}}

        # Delegate to BaseAgent for analysis
        response = await agent.process_query(
            f"Analyze the data. Use describe_result_summary, detect_data_types, analyze_numeric_distribution tools.",
            verbose=False
        )

        return {
            **state,
            "output": {
                "type": "analysis_done",
                "operation": operation,
                "analysis_result": response,
                "message": "Data analysis completed"
            }
        }

    async def data_transform(self, state: AgentState, agent) -> AgentState:
        """Transform or clean data using agent."""
        intent = state.get("intent", {})
        logger.info(f"[Excel] Data transform")

        if not agent:
            return {**state, "output": {"message": "No agent available"}}

        # Delegate to BaseAgent
        response = await agent.process_query(
            f"Transform the data. Use group_and_aggregate, pivot_analysis if needed.",
            verbose=False
        )

        return {
            **state,
            "output": {
                "type": "transform_done",
                "transform_result": response,
                "message": "Data transformation completed"
            }
        }

    async def chart_generate(self, state: AgentState, agent) -> AgentState:
        """Generate chart using agent."""
        intent = state.get("intent", {})
        chart_type = intent.get("chart_type", "bar")
        logger.info(f"[Excel] Chart generate: {chart_type}")

        if not agent:
            return {**state, "output": {"message": "No agent available"}}

        # Delegate to BaseAgent
        response = await agent.process_query(
            f"Create a {chart_type} chart. Use suggest_charts and render_chart tools.",
            verbose=False
        )

        return {
            **state,
            "chart_type": chart_type,
            "output": {
                "type": "chart_generated",
                "chart_type": chart_type,
                "chart_result": response,
                "message": f"{chart_type} chart generated"
            }
        }

    async def export(self, state: AgentState, agent) -> AgentState:
        """Export result to file using agent."""
        intent = state.get("intent", {})
        operation = intent.get("operation", "export")
        file_path = state.get("export_path")
        logger.info(f"[Excel] Export: {operation}")

        if not agent:
            return {**state, "output": {"message": "No agent available"}}

        # Delegate to BaseAgent
        response = await agent.process_query(
            f"Export the data to Excel file. Use export_excel tool.",
            verbose=False
        )

        return {
            **state,
            "output": {
                "type": "export_done",
                "operation": operation,
                "export_result": response,
                "message": "Export completed successfully"
            }
        }
