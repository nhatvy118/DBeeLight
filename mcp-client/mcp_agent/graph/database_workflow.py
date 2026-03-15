"""Database agent workflow with LangGraph - delegates to BaseAgent for tool execution."""

import logging
import json
from typing import Dict, Any
from openai import OpenAI

from mcp_agent.graph.base_workflow import BaseAgentWorkflow
from mcp_agent.graph.graph_state import AgentState
from mcp_agent.graph.state import (
    StageType,
    DATABASE_WORKFLOW,
)

logger = logging.getLogger(__name__)


class DatabaseAgentWorkflow(BaseAgentWorkflow):
    """Workflow for database agent.

    Stages:
    1. INTENT_PARSE - understand user request
    2. SCHEMA_DISCOVERY - get table/schema info (delegate to BaseAgent)
    3. SQL_GENERATION - build SQL query (delegate to BaseAgent)
    4. SQL_PREVIEW - show preview, wait for approval
    5. SQL_EXECUTION - run the query (delegate to BaseAgent)

    Each stage delegates to BaseAgent.process_query() for tool execution.
    """

    workflow_config = DATABASE_WORKFLOW

    def __init__(self, llm=None, agent=None):
        super().__init__(llm, agent)
        self.llm = llm or OpenAI()

    def get_stage_handlers(self) -> Dict[str, callable]:
        return {
            StageType.INTENT_PARSE.value: self.intent_parse,
            StageType.SCHEMA_DISCOVERY.value: self.schema_discovery,
            StageType.SQL_GENERATION.value: self.sql_generation,
            StageType.SQL_PREVIEW.value: self.sql_preview,
            StageType.SQL_EXECUTION.value: self.sql_execution,
        }

    async def intent_parse(self, state: AgentState, agent) -> AgentState:
        """Parse user intent and determine operation type."""
        user_message = state["user_message"]
        logger.info(f"[DB] Intent parse: {user_message[:50]}...")

        response = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Analyze the database request and extract:
                    - operation: SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, EXPORT
                    - tables: list of table names mentioned
                    - filters: WHERE conditions
                    - exports: if user wants to export to Excel
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
                "operation": "SELECT",
                "tables": [],
                "filters": {},
                "exports": "no",
                "detected_language": "en"
            }

        return {
            **state,
            "intent": intent,
            "detected_language": intent.get("detected_language", "en"),
            "tables": intent.get("tables", []),
        }

    async def schema_discovery(self, state: AgentState, agent) -> AgentState:
        """Discover schema for relevant tables.

        Delegates to BaseAgent to call MCP tools.
        """
        tables = state.get("tables", [])
        logger.info(f"[DB] Schema discovery for: {tables}")

        if not agent:
            # No agent, skip
            return {**state, "table_schema": {}}

        # Delegate to BaseAgent for tool execution
        if tables:
            # Ask agent to describe the tables
            tables_str = ", ".join(tables)
            response = await agent.process_query(
                f"Show me the schema for tables: {tables_str}. Use list_tables and describe_table tools.",
                verbose=False
            )
            logger.info(f"[DB] Schema discovery response: {response[:200]}...")

        return {
            **state,
            "table_schema": {"tables": tables},
        }

    async def sql_generation(self, state: AgentState, agent) -> AgentState:
        """Generate SQL query from intent.

        Delegates to BaseAgent to generate SQL using LLM + context.
        """
        intent = state.get("intent", {})
        user_message = state["user_message"]
        logger.info(f"[DB] SQL generation for: {intent.get('operation')}")

        operation = intent.get("operation", "SELECT").upper()

        # For simple SELECT, delegate to BaseAgent directly
        if operation == "SELECT" and not intent.get("exports"):
            if agent:
                response = await agent.process_query(
                    f"Generate and execute: {user_message}",
                    verbose=False
                )
                return {
                    **state,
                    "sql": response,
                    "query_result": response,
                    "output": {"type": "query_result", "data": response}
                }

        # For mutations or exports, generate SQL for preview
        response = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a SQL expert. Generate SQL query. Return ONLY the SQL."
                },
                {
                    "role": "user",
                    "content": f"Operation: {operation}\nTables: {intent.get('tables')}\nFilters: {intent.get('filters')}\nRequest: {user_message}"
                }
            ],
            temperature=0,
        )

        sql = response.choices[0].message.content.strip()

        # For mutations/SELECT with export, we need preview
        needs_preview = operation in ["INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"]
        needs_preview = needs_preview or intent.get("exports", "no") == "yes"

        return {
            **state,
            "sql": sql,
            "wait_user": needs_preview,
            "output": {
                "type": "sql_preview" if needs_preview else "sql_ready",
                "sql": sql,
                "message": "Please review and click Execute" if needs_preview else "Query ready"
            }
        }

    async def sql_preview(self, state: AgentState, agent) -> AgentState:
        """Show SQL preview and wait for user approval.

        If user has approved, proceed to execution.
        """
        approved = state.get("approved", False)
        sql = state.get("sql")

        logger.info(f"[DB] SQL preview, approved: {approved}")

        if not approved:
            # Stay at this stage, wait for user
            return {
                **state,
                "wait_user": True,
                "output": {
                    "type": "sql_preview",
                    "sql": sql,
                    "message": "Please review the SQL and click Execute to run"
                }
            }

        # User approved - proceed to execution
        return {
            **state,
            "wait_user": False,
        }

    async def sql_execution(self, state: AgentState, agent) -> AgentState:
        """Execute SQL query.

        Delegates to BaseAgent to execute via MCP.
        """
        sql = state.get("sql")
        logger.info(f"[DB] SQL execution: {sql[:50] if sql else 'None'}...")

        if not agent:
            return {
                **state,
                "output": {"error": "No agent available for execution"},
                "error": "No agent available"
            }

        # Delegate to BaseAgent to execute the SQL
        response = await agent.process_query(
            f"Execute this SQL: {sql}",
            verbose=False
        )

        return {
            **state,
            "query_result": response,
            "output": {
                "type": "execution_complete",
                "sql": sql,
                "result": response
            }
        }
