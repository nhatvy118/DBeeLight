"""
MCP Client Package

A client library for connecting to and interacting with MCP (Model Context Protocol) servers
using OpenAI GPT models. Supports multi-agent setup via BaseAgent and MultiAgentOrchestrator.
"""

from mcp_agent.database_agent import DatabaseAgent
from mcp_agent.excel_agent import ExcelAgent
from mcp_agent.base_agent import BaseAgent
from mcp_agent.orchestrator import MultiAgentOrchestrator
from mcp_agent.session import SessionManager

__all__ = [
    "BaseAgent",
    "DatabaseAgent",
    "ExcelAgent",
    "MultiAgentOrchestrator",
    "SessionManager",
]
__version__ = "0.1.0"
