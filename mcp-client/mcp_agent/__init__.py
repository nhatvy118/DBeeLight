"""
MCP Client Package

A client library for connecting to and interacting with MCP (Model Context Protocol) servers
using OpenAI GPT models. Supports multi-agent setup with approval-aware execution.

Layered structure:
- agents/       — BaseAgent, DatabaseAgent, ExcelAgent, ChartAgent
- orchestration/ — Orchestrator, IntentService
- session/     — SessionManager
- graph/       — LangGraph workflow (AgentWorkflow, per-agent workflows)
"""

# Agents
from mcp_agent.agents import BaseAgent, ChartAgent, DatabaseAgent, ExcelAgent

# Session
from mcp_agent.session import SessionManager

# Orchestration
from mcp_agent.orchestration import Orchestrator, IntentService, IntentResult

# LangGraph workflow
from mcp_agent.graph import AgentState, AgentWorkflow, StageType, SessionStatus

# Bundled MCP server scripts
from mcp_agent.servers import SERVER_SCRIPTS, SERVERS_DIR, server_script

__all__ = [
    # Agents
    "BaseAgent",
    "ChartAgent",
    "DatabaseAgent",
    "ExcelAgent",
    # Session
    "SessionManager",
    # Orchestration
    "Orchestrator",
    "IntentService",
    "IntentResult",
    # LangGraph
    "AgentWorkflow",
    "AgentState",
    "StageType",
    "SessionStatus",
    # Bundled servers
    "SERVER_SCRIPTS",
    "SERVERS_DIR",
    "server_script",
]

__version__ = "0.1.0"
