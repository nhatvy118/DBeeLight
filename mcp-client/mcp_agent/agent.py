"""Database Agent for intelligent query processing with MCP servers."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

from mcp_agent.session import SessionManager


class DatabaseAgent:
    """
    Intelligent AI agent for analyzing queries and deciding which tools to use.
    This agent has a detailed system prompt about each tool and best practices.
    """
    
    def __init__(self, model: str = "gpt-4o-mini", session_manager: Optional[SessionManager] = None):
        # MCP sessions - supports multiple servers
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        
        # OpenAI client
        self.openai = OpenAI()
        self.model = model
        
        # Cache tools from each server
        self._cached_tools: Dict[str, List] = {}
        
        # System prompt with detailed tool guidance
        self.system_prompt = self._build_system_prompt()
        
        # Session manager to save history
        if session_manager is None:
            raise ValueError("session_manager is required for DatabaseAgent")
        self.session_manager = session_manager
    
    def _build_system_prompt(self) -> str:
        """Build detailed system prompt about when to use which tool"""
        return """You are a professional Database Agent AI that helps users interact with PostgreSQL databases through available tools.

## IMPORTANT RULES:

### 1. DATABASE CONNECTION (MANDATORY FIRST STEP)
- **connect_db**: MUST call this tool BEFORE using any other tool
  - When user requests to work with database but not connected yet
  - When user provides database information (host, port, database name, username, password)
  - Example: "Connect to database localhost:5432, database: mydb, user: postgres, password: 123"
  
- **get_connection_info**: Check current connection status
  - When user asks "are we connected?" or "which database are we using?"
  
- **disconnect_database**: Disconnect from database
  - When user requests to disconnect or switch to another database

### 2. SCHEMA MANAGEMENT (DATABASE STRUCTURE)

- **list_tables**: List all tables
  - When user asks "what tables are there?", "show tables", "list all tables"
  - Should call BEFORE working with specific table to know which tables exist
  
- **describe_table**: View structure of a table
  - When user asks about table structure, columns, data types
  - Example: "structure of table users", "columns of table products"
  - Should call BEFORE SELECT/INSERT/UPDATE to know correct column names and types
  
- **get_schema**: View entire database schema
  - When user asks "database schema", "entire database structure"
  - Useful when needing to understand database overview
  
- **get_table_stats**: Statistics about table (row count, size)
  - When user asks "how many records?", "table size", "statistics"

### 3. CREATE AND MANAGE TABLES

- **create_table**: Create new table
  - When user requests "create table", "make table"
  - Requires columns definition and optional primary key
  - Example: "Create table users with id SERIAL, name VARCHAR(100), email VARCHAR(255)"
  
- **alter_table**: Modify table structure (add, delete, modify, rename columns)
  - **add_column**: Add new column to table
    - When user requests "add column", "add new column"
    - Requires column_name and column_def (e.g., "VARCHAR(255)", "INTEGER NOT NULL")
    - Example: "Add column email VARCHAR(255) to table users"
  
  - **drop_column**: Remove column from table
    - When user requests "drop column", "remove column"
    - Requires column_name
    - Example: "Drop column old_column from table users"
  
  - **modify_column**: Modify column (change type, add/remove NOT NULL, set default, etc.)
    - When user requests "modify column", "alter column", "change type"
    - Requires column_name and column_def
    - Example: "Modify column name to VARCHAR(200)", "Add NOT NULL to column email"
  
  - **rename_column**: Rename column
    - When user requests "rename column"
    - Requires column_name and new_column_name
    - Example: "Rename column old_name to new_name in table users"
  
- **create_db_from_spec**: Create schema from SQL DDL
  - When user provides complete SQL DDL statements
  - Useful when creating multiple tables at once
  
- **manage_constraint**: Add/remove constraints (CHECK, FOREIGN KEY, etc.)
  - When user requests to add or remove constraint
  
- **manage_trigger**: Create/remove triggers
  - When user requests to manage triggers

### 4. DATA OPERATIONS (CRUD)

- **select_data**: SELECT data from table
  - When user asks "show", "get", "select", "find", "view data"
  - Supports WHERE, ORDER BY, LIMIT
  - Example: "Get all users with age > 18", "Show first 10 products"
  - Should use this tool instead of execute_query for simple SELECTs
  
- **preview_table**: View table preview (default 10 rows)
  - When user wants "quick view", "preview", "sample data"
  - Useful to understand data structure before complex queries
  
- **insert_data**: INSERT data into table
  - When user requests "add", "insert", "create new record"
  - Requires dictionary with column names and values
  - Example: "Add new user: name='John', email='john@example.com'"
  
- **update_data**: UPDATE data in table
  - When user requests "update", "modify", "change"
  - Requires WHERE clause to identify rows to update
  - Example: "Update email of user with id=1 to 'new@example.com'"
  
- **delete_data**: DELETE data from table
  - When user requests "delete", "remove"
  - Requires WHERE clause to identify rows to delete
  - WARNING: Deleting data is a dangerous operation!

### 5. SQL QUERIES

- **execute_query**: Execute arbitrary SQL query
  - When user provides SQL query directly
  - When query is complex (JOIN, subquery, aggregation, etc.)
  - Example: "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
  - Should use for complex queries where simple tools are insufficient
  
- **run_mutation**: Run mutation query (INSERT/UPDATE/DELETE)
  - Similar to execute_query but only for mutations
  - Has validation to ensure safety
  
- **validate_sql**: Validate SQL syntax (does not execute)
  - When user wants to check SQL before running
  - Useful for debugging SQL errors
  
- **explain_sql**: View query execution plan
  - When user asks about performance, "why is query slow?"
  - Useful for optimizing queries

### 6. DOCUMENTATION

- **generate_schema_doc**: Generate documentation for schema
  - When user requests "create documentation", "export schema doc"
  - Supports text or markdown format

### 7. DATABASE MANAGEMENT

- **list_databases**: List all databases on server
  - When user asks "what databases are there?"

## OPTIMAL WORKFLOW:

1. **When user asks about database:**
   - Check connection (get_connection_info) → If not connected, request connect_db
   - If need to work with table: list_tables → describe_table (if needed) → perform operation

2. **When user requests SELECT:**
   - If simple query: use select_data
   - If complex query (JOIN, subquery): use execute_query
   - If just want quick view: use preview_table

3. **When user requests INSERT/UPDATE/DELETE:**
   - If simple: use insert_data/update_data/delete_data
   - If complex: use execute_query or run_mutation

4. **When user provides SQL directly:**
   - Validate first (validate_sql) if needed
   - Execute (execute_query or run_mutation)

5. **Always check schema before operations:**
   - describe_table to know correct column names and types
   - Avoid errors from wrong column names or type mismatches

## IMPORTANT NOTES:

- ALWAYS check connection before using other tools
- ALWAYS check table exists (list_tables) before operations
- ALWAYS check schema (describe_table) before INSERT/UPDATE to ensure correct columns
- BE CAREFUL with DELETE - always require confirmation or clear WHERE clause
- Prefer specialized tools (select_data, insert_data) over execute_query when possible
- When errors occur, read error message carefully and fix query/tool call

## EXAMPLE QUERIES:

User: "Connect to database localhost:5432, database: testdb, user: postgres, password: mypass"
→ connect_db(host="localhost", port=5432, database="testdb", username="postgres", password="mypass")

User: "What tables are there?"
→ list_tables()

User: "Structure of table users"
→ describe_table(table_name="users")

User: "Show all users"
→ select_data(table_name="users")

User: "Get users with age > 25, sorted by name"
→ select_data(table_name="users", where_clause="age > 25", order_by="name ASC")

User: "Add new user: name='Alice', email='alice@example.com', age=30"
→ insert_data(table_name="users", data={"name": "Alice", "email": "alice@example.com", "age": 30})

User: "Update email of user with id=1 to 'newemail@example.com'"
→ update_data(table_name="users", data={"email": "newemail@example.com"}, where_clause="id = 1")

User: "Add column email VARCHAR(255) to table users"
→ alter_table(action="add_column", table_name="users", column_name="email", column_def="VARCHAR(255)")

User: "Drop column old_column from table users"
→ alter_table(action="drop_column", table_name="users", column_name="old_column")

User: "Modify column name to VARCHAR(200) in table users"
→ alter_table(action="modify_column", table_name="users", column_name="name", column_def="VARCHAR(200)")

User: "Rename column old_name to new_name in table users"
→ alter_table(action="rename_column", table_name="users", column_name="old_name", new_column_name="new_name")

User: "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
→ execute_query(query="SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id")

Analyze the user's query and choose the most appropriate tool!"""

    async def connect_to_server(self, server_name: str, server_script_path: str):
        """Connect to an MCP server
        
        Args:
            server_name: Server identifier name (e.g., "database", "excel")
            server_script_path: Path to server script
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        script_path = Path(server_script_path).resolve()
        script_dir = script_path.parent
        
        if is_python:
            venv_dirs = [".venv", "venv", "env"]
            python_executable = None
            
            for venv_dir in venv_dirs:
                venv_path = script_dir / venv_dir
                if venv_path.exists() and venv_path.is_dir():
                    if sys.platform == "win32":
                        python_exe = venv_path / "Scripts" / "python.exe"
                    else:
                        python_exe = venv_path / "bin" / "python"
                    
                    if python_exe.exists():
                        python_executable = str(python_exe)
                        break
            
            if python_executable:
                command = python_executable
                args = [str(script_path)]
                print(f"[{server_name}] Using Python from venv: {python_executable}")
            else:
                command = "python"
                args = [server_script_path]
                print(f"[{server_name}] Using system Python: {command}")
        else:
            command = "node"
            args = [server_script_path]
        
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=None,
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(stdio, write)
        )

        await session.initialize()
        self.sessions[server_name] = session

        # Cache tools
        response = await session.list_tools()
        self._cached_tools[server_name] = response.tools
        print(f"[{server_name}] Connected! Available tools: {len(response.tools)}")
        
        # Print list of tools
        for tool in response.tools:
            print(f"  - {tool.name}: {tool.description[:80]}...")

    async def process_query(self, query: str, verbose: bool = False) -> str:
        """Process user query with intelligent AI agent
        
        Args:
            query: User query
            verbose: Print detailed information about tool calls
        """
        if not self.sessions:
            raise RuntimeError("No MCP servers connected. Please connect to at least one server first.")

        # Thu thập tất cả tools từ tất cả servers
        all_tools = []
        for server_name, tools in self._cached_tools.items():
            for tool in tools:
                all_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })

        # Load history from session (if available)
        history_messages = await self.session_manager.get_current_messages()
        
        # Create messages with system prompt and history
        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            }
        ]
        
        # Add history (skip old system messages if any)
        for msg in history_messages:
            if msg.get("role") != "system":  # Skip old system messages
                # Convert format from session format to OpenAI format
                message_dict = {
                    "role": msg["role"],
                    "content": msg["content"]
                }
                
                # Handle tool_calls if present
                if "tool_calls" in msg:
                    message_dict["tool_calls"] = msg["tool_calls"]
                
                # Handle tool messages (with tool_call_id)
                if msg["role"] == "tool":
                    try:
                        tool_data = json.loads(msg["content"])
                        message_dict["tool_call_id"] = tool_data.get("tool_call_id")
                        message_dict["name"] = tool_data.get("name")
                        message_dict["content"] = tool_data.get("content", msg["content"])
                    except (json.JSONDecodeError, TypeError):
                        # If parsing fails, keep original
                        pass
                
                messages.append(message_dict)
        
        # Add new query
        messages.append({
            "role": "user",
            "content": query,
        })
        
        # Save user query to session
        await self.session_manager.add_message("user", query)

        final_text_chunks = []
        max_iterations = 10  # Limit iterations to avoid infinite loop
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            
            try:
                completion = self.openai.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools if all_tools else None,
                    tool_choice="auto",
                    temperature=0.1,  # Reduce randomness for more accurate tool selection
                )

                message = completion.choices[0].message
                content_text = message.content or ""
                if content_text:
                    final_text_chunks.append(content_text)

                tool_calls = message.tool_calls or []

                if not tool_calls:
                    # No more tool calls, this is the final response
                    # Save final assistant response to session
                    if content_text:
                        await self.session_manager.add_message("assistant", content_text)
                    break

                assistant_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(assistant_message)
                
                # Save assistant message with tool calls to session
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
                await self.session_manager.add_message(
                    "assistant", 
                    message.content or "", 
                    tool_calls=tool_calls_data
                )

                # Find which server has this tool and call it
                for tc in tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        tool_args = {}
                        if verbose:
                            print(f"⚠️  Warning: Failed to parse arguments for {tool_name}")

                    # Find server that has this tool
                    target_server = None
                    for server_name, tools in self._cached_tools.items():
                        if any(t.name == tool_name for t in tools):
                            target_server = server_name
                            break

                    if target_server is None:
                        error_msg = f"Tool '{tool_name}' not found in any connected server"
                        if verbose:
                            print(f"❌ {error_msg}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": json.dumps({"error": error_msg}),
                        })
                        continue

                    if verbose:
                        print(f"🔧 [{target_server}] Calling {tool_name} with args: {tool_args}")

                    try:
                        result = await self.sessions[target_server].call_tool(tool_name, tool_args)
                        result_content = result.content

                        if not isinstance(result_content, str):
                            result_content = str(result_content)

                        if verbose:
                            print(f"✅ [{target_server}] {tool_name} returned: {result_content[:200]}...")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": json.dumps(result_content),
                        })
                        
                        # Save tool result to session (special format for tool messages)
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": result_content
                        }
                        # Save as JSON string for easier parsing later
                        await self.session_manager.add_message(
                            "tool",
                            json.dumps(tool_message)
                        )
                    except Exception as e:
                        error_msg = f"Error calling {tool_name}: {str(e)}"
                        if verbose:
                            print(f"❌ {error_msg}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": json.dumps({"error": error_msg}),
                        })

            except Exception as e:
                error_msg = f"Error in iteration {iteration}: {str(e)}"
                if verbose:
                    print(f"❌ {error_msg}")
                final_text_chunks.append(f"Error: {error_msg}")
                break

        if iteration >= max_iterations:
            final_text_chunks.append("\n⚠️  Reached maximum iterations. Please simplify your query.")

        final_response = "\n".join(chunk for chunk in final_text_chunks if chunk)
        
        return final_response

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()
