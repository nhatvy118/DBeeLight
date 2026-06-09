"""Tool backend — abstracts where a tool runs.

- InProcessBackend: calls Python functions directly (database/chart).
- ExcelHttpBackend: talks MCP over streamable-http to the excel-server.

Agent/workflow just calls backend.call_tool(name, args) — no need to know which backend.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from app.agent.tools import registry

logger = logging.getLogger("agent.backend")


@dataclass
class ToolResult:
    content: str
    is_error: bool = False

    def to_tool_message(self) -> str:
        return self.content


class ToolBackend(Protocol):
    def owns(self, name: str) -> bool: ...
    def list_tools_openai(self) -> list[dict]: ...
    async def call_tool(self, name: str, args: dict) -> ToolResult: ...


class InProcessBackend:
    """Dispatch tool name → registry function. The function reads the ContextVar."""

    def __init__(self, tool_names: list[str]):
        self._names = [n for n in tool_names if registry.has(n)]

    def owns(self, name: str) -> bool:
        return name in self._names

    def list_tools_openai(self) -> list[dict]:
        return registry.openai_schemas(self._names)

    async def call_tool(self, name: str, args: dict) -> ToolResult:
        spec = registry.get(name)
        try:
            out = await spec.fn(**(args or {}))
            return ToolResult(content=out if isinstance(out, str) else json.dumps(out, default=str))
        except Exception as e:  # noqa: BLE001
            logger.exception("InProcess tool %s failed: %s", name, e)
            return ToolResult(content=json.dumps({"error": str(e)}), is_error=True)


class ExcelHttpBackend:
    """MCP client over streamable-http to the excel-server.

    The server runs stateless_http, so a short per-call session is cheap.
    The tool list is fetched once then cached.
    """

    def __init__(self, url: str):
        self._url = url
        self._schemas: list[dict] | None = None
        self._tool_names: set[str] = set()

    def owns(self, name: str) -> bool:
        return name in self._tool_names

    async def _session(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        return streamablehttp_client(self._url), ClientSession

    async def refresh(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(self._url) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                resp = await session.list_tools()
        self._schemas = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                },
            }
            for t in resp.tools
        ]
        self._tool_names = {t.name for t in resp.tools}

    def list_tools_openai(self) -> list[dict]:
        return self._schemas or []

    async def call_tool(self, name: str, args: dict) -> ToolResult:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        try:
            async with streamablehttp_client(self._url) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    result = await session.call_tool(name, args or {})
            parts = [getattr(b, "text", "") for b in (result.content or [])]
            return ToolResult(content="".join(p for p in parts if p), is_error=bool(result.isError))
        except Exception as e:  # noqa: BLE001
            logger.exception("Excel HTTP tool %s failed: %s", name, e)
            return ToolResult(content=json.dumps({"error": str(e)}), is_error=True)
