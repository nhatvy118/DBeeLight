"""
MCP Client Package

A client library for connecting to and interacting with MCP (Model Context Protocol) servers
using OpenAI GPT models. Supports multi-agent setup via BaseAgent and MultiAgentOrchestrator.

Now includes Hybrid approach with IntentRouter:
- Simple queries → LLM-driven (fast, direct tool calls)
- Complex queries → LangGraph workflow (sequential stages + approval)
"""

from mcp_agent.database_agent import DatabaseAgent
from mcp_agent.excel_agent import ExcelAgent
from mcp_agent.base_agent import BaseAgent
from mcp_agent.orchestrator import MultiAgentOrchestrator
from mcp_agent.session import SessionManager

# Intent Router
from mcp_agent.intent_router import IntentRouter, QueryComplexity, QueryIntent

# Hybrid Orchestrator
from mcp_agent.hybrid_orchestrator import HybridOrchestrator

# LangGraph components (optional, requires langgraph package)
try:
    from mcp_agent.graph import AgentWorkflow, GraphState, StageType, SessionStatus
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

__all__ = [
    "BaseAgent",
    "DatabaseAgent",
    "ExcelAgent",
    "MultiAgentOrchestrator",
    "SessionManager",
    # Intent Router
    "IntentRouter",
    "QueryComplexity",
    "QueryIntent",
    # Hybrid Orchestrator
    "HybridOrchestrator",
    # LangGraph exports
    "AgentWorkflow",
    "GraphState",
    "StageType",
    "SessionStatus",
    "LANGGRAPH_AVAILABLE",
]
__version__ = "0.1.0"
