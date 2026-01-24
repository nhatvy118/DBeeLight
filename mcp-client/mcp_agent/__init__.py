"""
MCP Client Package

A client library for connecting to and interacting with MCP (Model Context Protocol) servers
using OpenAI GPT models.
"""

from mcp_agent.agent import DatabaseAgent
from mcp_agent.session import SessionManager

__all__ = ["DatabaseAgent", "SessionManager"]
__version__ = "0.1.0"
