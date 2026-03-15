# MCP Client

Python package for connecting to and interacting with MCP (Model Context Protocol) servers using OpenAI GPT models.

## Installation

1. Install dependencies:
```bash
cd mcp-client
uv sync
```

2. Create `.env` file with OpenAI API key:
```bash
echo "OPENAI_API_KEY=your_api_key_here" > .env
```

## Requirements

- `.env` file with `OPENAI_API_KEY`
- Python 3.12+

## Architecture: Hybrid Orchestrator

This package uses a **Hybrid Orchestrator** approach that combines:

1. **LLM-driven** (simple queries) - Fast, direct tool calls
2. **LangGraph Workflow** (complex queries) - Sequential stages with human approval
3. **Intent Router** - Classifies queries to determine handling approach

### Flow Diagram

```
User Prompt
      │
      ▼
┌──────────────────┐
│  IntentRouter    │  ← LLM classifies: simple / complex / conversational
│  .classify()     │
└────────┬─────────┘
         │
    ┌────┴────┬────────────┐
    ▼         ▼            ▼
Simple   Complex    Conversational
    │         │            │
    ▼         ▼            ▼
LLM-driven  Workflow   Continue
(BaseAgent)  (LangGraph) conversation
```

### Query Classification

| Query Type | Approach | Description |
|------------|---------|-------------|
| "list tables" | simple | Direct tool call |
| "show schema" | simple | Direct tool call |
| "select *" | simple | Direct tool call |
| "insert data" | **complex** | SQL preview → user approval → execute |
| "create report" | **complex** | Multi-step workflow |
| "analyze + chart" | **complex** | Sequential stages |

### LangGraph Workflow

Each agent (database, excel) has its own workflow:

**Database Agent:**
```
INTENT_PARSE → SCHEMA_DISCOVERY → SQL_GENERATION → SQL_PREVIEW (wait) → SQL_EXECUTION
```

**Excel Agent:**
```
INTENT_PARSE → FILE_LOAD → DATA_ANALYZE → DATA_TRANSFORM → CHART_GENERATE → EXPORT
```

Nodes in the workflow **delegate to BaseAgent** for tool execution.

## Features

### Automatic Virtual Environment Detection
- Automatically detects and uses Python from server's `.venv` (if available)
- Ensures server runs with correct dependencies
- Falls back to system Python if venv not found

### Tool Caching
- Tools are cached after connection for better performance
- No need to list tools again for each query

### Session Management
- Automatic session creation and management
- Persistent chat history per user
- Support for multiple concurrent sessions
- Sessions are stored in Postgres table `session` (id, user_id, content JSONB)

### Human-in-the-Loop
- Complex queries that modify data require user approval
- SQL preview shown before execution
- Supports approval workflow via `approve_and_execute()`

## Package Structure

```
mcp-client/
├── mcp_agent/                    # Main package
│   ├── __init__.py              # Exports
│   ├── base_agent.py             # BaseAgent class
│   ├── database_agent.py         # Database agent
│   ├── excel_agent.py            # Excel agent
│   ├── orchestrator.py           # Legacy orchestrator
│   ├── intent_router.py         # Intent classification
│   ├── hybrid_orchestrator.py    # Hybrid orchestrator
│   ├── session.py               # Session manager
│   └── graph/                   # LangGraph workflows
│       ├── __init__.py
│       ├── state.py              # State types
│       ├── graph_state.py        # TypedDict state
│       ├── base_workflow.py      # Base workflow class
│       ├── database_workflow.py  # Database workflow
│       ├── excel_workflow.py     # Excel workflow
│       └── workflow.py           # Main workflow
└── pyproject.toml               # Package configuration
```

## Usage as Library

### Basic Usage (LLM-driven)

```python
from mcp_agent import DatabaseAgent, SessionManager

# Create session manager (Postgres-backed)
session_manager = SessionManager(db_pool=pool, user_id="user-123")

# Create agent
agent = DatabaseAgent(model="gpt-4o-mini", session_manager=session_manager)

# Connect to MCP servers
await agent.connect_to_server("database", "../database/database.py")

# Process queries
response = await agent.process_query("Show all users")
```

### Using HybridOrchestrator (Recommended)

```python
from mcp_agent import HybridOrchestrator, DatabaseAgent, ExcelAgent, SessionManager

# Create session manager
session_manager = SessionManager(db_pool=pool, user_id="user-123")

# Create agents
db_agent = DatabaseAgent(model="gpt-4o-mini", session_manager=session_manager, agent_id="database")
excel_agent = ExcelAgent(model="gpt-4o-mini", session_manager=session_manager, agent_id="excel")

# Connect to MCP servers
await db_agent.connect_to_server("database", "../database/database.py")
await excel_agent.connect_to_server("excel", "../excel-summary/excel_summary.py")

# Create hybrid orchestrator
orchestrator = HybridOrchestrator(
    agents=[db_agent, excel_agent],
    session_manager=session_manager,
)

# Process queries - automatically routes based on query type
result = await orchestrator.process_query("Show all tables")
# Returns: {"response": "...", "agent_id": "database", "approach": "llm_driven", "intent": {...}}

result = await orchestrator.process_query("Insert into users values ('John')")
# Returns: {"response": "Please review SQL...", "approach": "workflow", ...}

# Execute after user approval
await orchestrator.approve_and_execute(session_id, approved=True)
```

### Using IntentRouter Directly

```python
from mcp_agent import IntentRouter, QueryComplexity

router = IntentRouter()

# Classify query
result = await router.classify("Show me all tables")
# Returns: {"intent": "list_tables", "complexity": "simple", "requires_approval": False, ...}

# Route to handler
approach = await router.route("Show me all tables")
# Returns: "llm_driven" | "workflow" | "conversational"
```

## API Reference

### Classes

| Class | Description |
|-------|-------------|
| `BaseAgent` | Base class for MCP agents |
| `DatabaseAgent` | Agent for database operations |
| `ExcelAgent` | Agent for Excel operations |
| `SessionManager` | Manages chat sessions |
| `HybridOrchestrator` | Hybrid orchestrator with IntentRouter |
| `IntentRouter` | Query classification |
| `AgentWorkflow` | LangGraph workflow builder |

### Enums

| Enum | Values |
|------|--------|
| `QueryComplexity` | simple, complex, conversational |
| `QueryIntent` | list_tables, select_query, insert_data, etc. |

## Notes

- Supports both Python (`.py`) and JavaScript (`.js`) MCP servers
- Ensure servers have dependencies installed before connecting
- Uses OpenAI GPT-4o-mini by default (can be changed in code)
- Designed to be installed and used as a library in other projects
- Used by `api-server` to provide REST API interface
- Requires Postgres table `session` (id, user_id, content JSONB)
