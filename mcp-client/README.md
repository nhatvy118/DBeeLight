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

## Package Structure

```
mcp-client/
├── mcp_agent/           # Package
│   ├── __init__.py      # Exports DatabaseAgent, SessionManager
│   ├── agent.py         # DatabaseAgent class
│   └── session.py       # SessionManager class
└── pyproject.toml       # Package configuration
```

## Usage as Library

This package is designed to be used as a library in other projects:

```python
from mcp_agent import DatabaseAgent, SessionManager

# Create session manager (Postgres-backed)
# pool is an asyncpg.Pool created by your application
session_manager = SessionManager(db_pool=pool, user_id="user-123")

# Create agent
agent = DatabaseAgent(model="gpt-4o-mini", session_manager=session_manager)

# Connect to MCP servers
await agent.connect_to_server("database", "../database/database.py")
await agent.connect_to_server("excel", "../excel-summary/excel_summary.py")

# Process queries
response = await agent.process_query("Show all users")
```

## Notes

- Supports both Python (`.py`) and JavaScript (`.js`) MCP servers
- Ensure servers have dependencies installed before connecting
- Uses OpenAI GPT-4o-mini by default (can be changed in code)
- Designed to be installed and used as a library in other projects
- Used by `api-server` to provide REST API interface
- Requires Postgres table `session` (id, user_id, content JSONB)

