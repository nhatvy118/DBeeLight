"""Superset agent workflow with LangGraph - each workflow defines its own stages."""

import logging
import json
import os
import re
from typing import Dict, Any
from openai import OpenAI
from langgraph.graph import StateGraph, END

from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import StageType

logger = logging.getLogger(__name__)


class SupersetAgentWorkflow:
    """Workflow for Superset visualization agent - each stage defined independently."""

    def __init__(self, llm=None, agent=None, database_agent=None):
        self.llm = llm or OpenAI()
        self.agent = agent
        self.database_agent = database_agent

    async def _call_tool(self, agent, tool_name: str, args: dict) -> str:
        """Call MCP tool directly through agent sessions."""
        if not agent:
            raise RuntimeError("No agent available")

        for _server_name, session in agent.sessions.items():
            try:
                result = await session.call_tool(tool_name, args)
                content = result.content
                if hasattr(content, "text"):
                    return str(content.text)
                if isinstance(content, list) and content:
                    first = content[0]
                    if hasattr(first, "text"):
                        return str(first.text)
                return str(content)
            except Exception as e:
                logger.warning(f"[Superset] Tool '{tool_name}' failed: {e}")
                continue

        raise RuntimeError(f"Tool '{tool_name}' not found in connected sessions")

    async def _call_agent(self, agent, prompt: str) -> str:
        """Delegate to BaseAgent's tool loop for multi-step operations."""
        if not agent:
            return "No agent available"
        return await agent.process_query(prompt, verbose=False, persist_history=False)

    def get_stage_handlers(self) -> Dict[str, callable]:
        return {
            StageType.INTENT_PARSE.value: self.intent_parse,
            StageType.SCHEMA_DISCOVERY.value: self.schema_discovery,
            "DB_CONNECTION": self.db_connection,
            StageType.SQL_EXECUTION.value: self.sql_execution,
            "CHART_CREATION": self.chart_creation,
            "CHART_EMBED": self.chart_embed,
        }

    def _build_graph(self) -> Any:
        """Build LangGraph for Superset workflow."""
        workflow = StateGraph(AgentState)
        handlers = self.get_stage_handlers()

        # Add all stage nodes
        stage_order = [
            StageType.INTENT_PARSE.value,
            "DB_CONNECTION",
            StageType.SCHEMA_DISCOVERY.value,
            StageType.SQL_EXECUTION.value,
            "CHART_CREATION",
            "CHART_EMBED",
        ]

        for stage_name in stage_order:
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
            first = stage_order[0] if stage_order else StageType.INTENT_PARSE.value
            return {**state, "current_stage": first}

        workflow.add_node("START", start_handler)

        async def done_handler(state):
            return {**state, "current_stage": StageType.DONE.value}

        workflow.add_node(StageType.DONE.value, done_handler)

        workflow.set_entry_point("START")
        workflow.add_edge("START", stage_order[0])

        # Linear flow
        for i in range(len(stage_order) - 1):
            workflow.add_edge(stage_order[i], stage_order[i + 1])

        workflow.add_edge(stage_order[-1], StageType.DONE.value)
        workflow.add_edge(StageType.DONE.value, END)

        return workflow.compile()

    async def run(self, session_id: str, user_message: str) -> AgentState:
        """Run the workflow."""
        state = create_initial_state(session_id, user_message, "superset")
        graph = self._build_graph()
        result = await graph.ainvoke(state)
        return result

    async def intent_parse(self, state: AgentState, _agent) -> AgentState:
        """Parse user visualization intent."""
        user_message = state["user_message"]
        logger.info(f"[Superset] Intent parse: {user_message[:80]}...")

        response = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Analyze the visualization request and extract:
- chart_type: bar, line, pie, table, timeseries, heatmap, etc.
- metrics: what to measure/aggregate
- dimensions: how to group/categorize
- filters: any WHERE conditions mentioned
- detected_language: en or vi

Return strict JSON."""
                },
                {"role": "user", "content": user_message}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        try:
            intent = json.loads(response.choices[0].message.content)
        except:
            intent = {"chart_type": "bar", "metrics": "", "dimensions": "", "filters": "", "detected_language": "en"}

        return {
            **state,
            "intent": intent,
            "detected_language": intent.get("detected_language", "en"),
            "chart_type": intent.get("chart_type", "bar"),
        }

    async def db_connection(self, state: AgentState, agent) -> AgentState:
        """Check if database is registered in Superset, register if needed."""
        logger.info("[Superset] Checking Superset database connection...")

        if not agent:
            return {**state, "error": "No Superset agent available"}

        # Check Superset status first
        try:
            status = await self._call_tool(agent, "superset_status", {})
            logger.info(f"[Superset] Status: {status[:200]}")
        except Exception as e:
            logger.warning(f"[Superset] Status check failed: {e}")

        # Step 1: Get actual database URI from database agent
        db_uri = ""
        db_name = ""
        if self.database_agent:
            try:
                db_info = await self._call_tool(self.database_agent, "get_connection_info", {})
                logger.info(f"[Superset] DB connection info: {db_info[:200]}")

                # Parse URI from connection info
                # Format: "Current database connection:\n- Type: SQLite\n- File: /path/to/file.db"
                m = re.search(r"Type:\s*(\w+)", db_info, re.IGNORECASE)
                db_type = m.group(1).lower() if m else ""

                if "sqlite" in db_type:
                    m_path = re.search(r"File:\s*([^\n]+)", db_info)
                    if m_path:
                        file_path = m_path.group(1).strip()
                        db_uri = f"sqlite:///{file_path}"
                elif "postgresql" in db_type or "postgres" in db_type:
                    # PostgreSQL: extract host, port, dbname from connection info
                    # For now, fall back to env var or stored config
                    db_uri = os.getenv("PROJECT_DB_URI", "")

                # Extract project identifier from file path for DB name
                m_proj = re.search(r"/([^/]+)\.db", db_info)
                if m_proj:
                    db_name = f"project_{m_proj.group(1).replace('.db', '')}"
            except Exception as e:
                logger.warning(f"[Superset] Failed to get DB connection info: {e}")

        # Step 2: Check if already registered
        try:
            dbs_raw = await self._call_tool(agent, "list_superset_databases", {})
            dbs = json.loads(dbs_raw) if dbs_raw else []
            existing = [db for db in dbs if isinstance(db, dict) and db.get("database_name", "").lower() == db_name.lower()]
            if existing:
                logger.info(f"[Superset] Database '{db_name}' already registered, skipping registration.")
                return {
                    **state,
                    "output": {"type": "db_connection", "message": f"Database '{db_name}' already registered."},
                }
        except Exception as e:
            logger.warning(f"[Superset] Failed to list databases: {e}")

        # Step 3: Register database with actual URI
        if not db_uri:
            return {
                **state,
                "error": "No database URI available. Please connect to a database first.",
                "output": {"type": "db_connection", "message": "No database connection found. Please connect to a database before creating charts."},
            }

        try:
            reg_result = await self._call_tool(agent, "register_database", {
                "name": db_name,
                "sqlalchemy_uri": db_uri,
            })
            logger.info(f"[Superset] register_database result: {reg_result[:500]}")

            # Check if result indicates an error
            if "error" in reg_result.lower() or "fail" in reg_result.lower() or "400" in reg_result or "500" in reg_result:
                return {
                    **state,
                    "error": f"Database registration failed: {reg_result}",
                    "output": {"type": "db_connection", "message": reg_result},
                }

            return {
                **state,
                "output": {"type": "db_connection", "message": reg_result},
            }
        except Exception as e:
            return {
                **state,
                "error": f"Failed to register database: {e}",
                "output": {"type": "db_connection", "message": f"Failed to register database: {e}"},
            }

    async def schema_discovery(self, state: AgentState, agent) -> AgentState:
        """Get available tables from Superset."""
        logger.info("[Superset] Schema discovery...")

        if not agent:
            return {**state, "error": "No Superset agent available"}

        response = await self._call_agent(
            agent,
            f"Show available tables in Superset. Use list_superset_databases and get_database_tables."
        )

        return {
            **state,
            "output": {"type": "schema_discovery", "message": response},
        }

    async def sql_execution(self, state: AgentState, agent) -> AgentState:
        """Execute SQL query via Superset SQL Lab."""
        logger.info("[Superset] SQL execution...")

        if not agent:
            return {**state, "error": "No Superset agent available"}

        # Delegate full query + chart flow to BaseAgent
        response = await self._call_agent(
            agent,
            f"Execute the SQL query for the chart and create a virtual dataset. "
            f"User request: {state['user_message']}"
        )

        return {
            **state,
            "output": {"type": "sql_execution", "message": response},
        }

    async def chart_creation(self, state: AgentState, agent) -> AgentState:
        """Create chart in Superset."""
        logger.info("[Superset] Chart creation...")

        if not agent:
            return {**state, "error": "No Superset agent available"}

        response = await self._call_agent(
            agent,
            f"Create the chart in Superset using create_virtual_dataset and create_chart. "
            f"Chart type from intent: {state.get('chart_type', 'bar')}. "
            f"User request: {state['user_message']}"
        )

        return {
            **state,
            "output": {"type": "chart_creation", "message": response},
        }

    async def chart_embed(self, state: AgentState, agent) -> AgentState:
        """Generate chart embed URL and prepare for iframe display."""
        logger.info("[Superset] Chart embed URL generation...")

        if not agent:
            return {**state, "error": "No Superset agent available"}

        response = await self._call_agent(
            agent,
            f"Get the embed URL for the chart using get_chart_embed_url. "
            f"Include [CHART_EMBED_URL_START]<url>[CHART_EMBED_URL_END] marker in your response. "
            f"User request: {state['user_message']}"
        )

        # Extract embed URL for iframe
        embed_url = None
        try:
            match = json.loads(response)
            if isinstance(match, dict):
                embed_url = match.get("embed_url") or match.get("fullscreen_url")
        except:
            m = re.search(r'\[CHART_EMBED_URL_START\](.*?)\[CHART_EMBED_URL_END\]', response)
            if m:
                embed_url = m.group(1).strip()

        return {
            **state,
            "chart_data": {"embed_url": embed_url},
            "output": {"type": "chart_embed", "message": response, "embed_url": embed_url},
        }
