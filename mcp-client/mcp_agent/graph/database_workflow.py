"""Database agent workflow with LangGraph - delegates to BaseAgent for tool execution."""

import logging
import json
from typing import Dict
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

    async def _call_tool(self, agent, tool_name: str, args: dict) -> str:
        """Call MCP tool directly through agent sessions (no internal prompt)."""
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
            except Exception:
                continue

        raise RuntimeError(f"Tool '{tool_name}' not found in connected sessions")

    async def _safe_list_tables_and_describe(self, agent, tables: list[str]) -> str:
        """Run list_tables + describe_table directly for discovery/logging."""
        logs: list[str] = []
        try:
            tables_result = await self._call_tool(agent, "list_tables", {})
            logs.append(f"list_tables: {tables_result}")
        except Exception as e:
            logs.append(f"list_tables error: {e}")

        for t in tables:
            try:
                d = await self._call_tool(agent, "describe_table", {"table_name": t})
                logs.append(f"describe_table({t}): {d}")
            except Exception as e:
                logs.append(f"describe_table({t}) error: {e}")

        return "\n".join(logs)

    async def _extract_create_table_args(self, user_message: str) -> dict:
        """Extract create-table tool args from user request as JSON."""
        resp = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract arguments for show_create_table_schema tool from user request. "
                        "Return strict JSON with keys: table_name (string), columns (string), primary_key (string|null). "
                        "columns must be SQL column list like: 'id SERIAL, name VARCHAR(100), dob DATE'."
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        table_name = str(data.get("table_name") or "").strip()
        columns = str(data.get("columns") or "").strip()
        primary_key = data.get("primary_key")
        if primary_key is not None:
            primary_key = str(primary_key).strip() or None

        if not table_name or not columns:
            raise RuntimeError("Could not extract create_table arguments from user request")

        return {
            "table_name": table_name,
            "columns": columns,
            "primary_key": primary_key,
        }

    async def intent_parse(self, state: AgentState, _agent) -> AgentState:
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

        # Direct MCP tool calls (no internal prompt text)
        if tables:
            response = await self._safe_list_tables_and_describe(agent, tables)
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

        # CREATE TABLE special flow in workflow:
        # 1) Always call show_create_table_schema first
        # 2) Return tool output for frontend schema dropdown
        # 3) Do not execute create directly here
        if operation == "CREATE" and agent:
            try:
                args = await self._extract_create_table_args(user_message)
                schema_response = await self._call_tool(agent, "show_create_table_schema", args)
            except Exception as e:
                schema_response = f"Error preparing schema preview: {e}"

            return {
                **state,
                "wait_user": True,
                "output": {
                    "type": "schema_preview",
                    "message": schema_response,
                },
            }

        # For simple SELECT, delegate to BaseAgent directly
        if operation == "SELECT" and not intent.get("exports"):
            if agent:
                response = await agent.process_query(
                    f"Generate and execute: {user_message}",
                    verbose=False,
                    persist_history=False,
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

    async def sql_preview(self, state: AgentState, _agent) -> AgentState:
        """Show SQL preview and wait for user approval.

        If user has approved, proceed to execution.
        """
        approved = state.get("approved", False)
        sql = state.get("sql")

        logger.info(f"[DB] SQL preview, approved: {approved}")

        # Preserve CREATE TABLE schema preview payload produced at SQL_GENERATION stage.
        # Do not overwrite it with generic SQL preview text.
        output = state.get("output") or {}
        if output.get("type") == "schema_preview":
            return {
                **state,
                "wait_user": True,
                "output": output,
            }

        if not approved:
            # Wait for user approval
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

        # Direct MCP tool call to execute SQL (no internal prompt)
        try:
            response = await self._call_tool(agent, "execute_query", {"query": sql})
        except Exception as e:
            response = f"Error executing SQL: {e}"

        return {
            **state,
            "query_result": response,
            "output": {
                "type": "execution_complete",
                "sql": sql,
                "result": response
            }
        }
