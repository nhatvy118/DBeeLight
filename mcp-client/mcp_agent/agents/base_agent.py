"""Base MCP Agent for multi-agent architecture."""

import asyncio
import json
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

from mcp_agent.session.session_manager import SessionManager

try:
    from langchain_core.messages.utils import count_tokens_approximately
except ImportError:
    def count_tokens_approximately(text: str) -> int:
        return max(1, len(text) // 4)


TOOL_RESULT_MAX_TOKENS = max(512, int(os.getenv("TOOL_RESULT_MAX_TOKENS", "4000")))


def _cap_tool_json_payload(raw: str, max_tokens: int) -> str:
    if count_tokens_approximately(raw) <= max_tokens:
        return raw
    # ~4 chars per token heuristic
    limit_chars = max(500, max_tokens * 4)
    return raw[:limit_chars] + '\n...[tool output truncated]'


class BaseAgent(ABC):
    """
    Base class for MCP-backed agents. Handles server connections, tool caching,
    and the chat/tool-call loop. Subclasses define system prompt and behavior.
    """

    def __init__(
        self,
        agent_id: str,
        model: str = "gpt-4o-mini",
        session_manager: Optional[SessionManager] = None,
    ):
        self.agent_id = agent_id
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.openai = OpenAI()
        self.model = model
        self._cached_tools: Dict[str, List] = {}
        if session_manager is None:
            raise ValueError("session_manager is required")
        self.session_manager = session_manager
        self.system_prompt = self._build_system_prompt()

    @abstractmethod
    def _build_system_prompt(self) -> str:
        """Build the system prompt for this agent. Must be implemented by subclasses."""
        pass

    async def connect_to_server(
        self,
        server_name: str,
        server_script_path: str,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Connect to an MCP server.

        Args:
            server_name: Server identifier (e.g. "database", "excel").
            server_script_path: Path to server script (.py or .js).
            env: Extra env vars to pass into the spawned subprocess. Merged on
                top of the current process env so the child still inherits
                ``PATH``, ``DATABASE_URL``, etc. Use this for per-user
                context (e.g. ``USER_GOOGLE_SUB``) when the server needs to
                act on behalf of a specific app user.
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
            else:
                command = "python"
                args = [server_script_path]
        else:
            command = "node"
            args = [server_script_path]

        merged_env: Dict[str, str] = {**os.environ}
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items() if v is not None})

        server_params = StdioServerParameters(command=command, args=args, env=merged_env)
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
        await session.initialize()
        self.sessions[server_name] = session
        response = await session.list_tools()
        self._cached_tools[server_name] = response.tools

    def get_all_tools_for_openai(self) -> List[Dict[str, Any]]:
        """Collect all tools from all connected servers in OpenAI function format."""
        out: List[Dict[str, Any]] = []
        for tools in self._cached_tools.values():
            for tool in tools:
                out.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })
        return out

    async def process_query(self, query: str, verbose: bool = False, persist_history: bool = True) -> str:
        """Process user query: load history, call LLM with tools, execute tool calls, return final text.

        Args:
            query: Input text for this tool loop.
            verbose: Print tool-call logs.
            persist_history: If False, do not persist this run into session history.
        """
        if not self.sessions:
            raise RuntimeError(
                f"Agent {self.agent_id}: No MCP servers connected. Connect at least one server first."
            )

        all_tools = self.get_all_tools_for_openai()
        history_messages = await self.session_manager.get_llm_context_messages()

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        # Only load user + final assistant (no tool_calls) from history to avoid OpenAI 400:
        # "tool" must follow "assistant" with matching tool_calls; ids from old turns don't match.
        for msg in history_messages:
            if msg.get("role") == "system":
                continue
            role = msg.get("role")
            if role == "tool":
                continue
            if role == "assistant" and msg.get("tool_calls"):
                continue
            messages.append({
                "role": role,
                "content": msg.get("content", ""),
            })

        messages.append({"role": "user", "content": query})
        if persist_history:
            await self.session_manager.add_message("user", query)

        final_chunks: List[str] = []
        max_iterations = 5
        iteration = 0
        hit_iteration_limit = True

        while iteration < max_iterations:
            iteration += 1
            try:
                completion = self.openai.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools if all_tools else None,
                    tool_choice="auto",
                    temperature=0.1,
                )
                message = completion.choices[0].message
                content_text = message.content or ""
                if content_text:
                    final_chunks.append(content_text)
                tool_calls = message.tool_calls or []

                # Only save assistant message when it's the FINAL answer (no more tool_calls)
                if not tool_calls:
                    if content_text and persist_history:
                        await self.session_manager.add_message("assistant", content_text)
                    hit_iteration_limit = False
                    break

                # Don't save intermediate assistant messages (with tool_calls)
                # Only keep them in memory for the current conversation loop
                assistant_message: Dict[str, Any] = {
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
                # Do NOT save intermediate assistant messages with tool_calls
                # Only save final answer when loop ends (no tool_calls)

                for tc in tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        tool_args = {}
                    target_server = None
                    for server_name, tools in self._cached_tools.items():
                        if any(t.name == tool_name for t in tools):
                            target_server = server_name
                            break
                    if target_server is None:
                        err = json.dumps({"error": f"Tool '{tool_name}' not found in any connected server"})
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id, "name": tool_name, "content": err,
                        })
                        continue
                    print(f"[{self.agent_id}] [{target_server}] Calling tool: {tool_name} {tool_args}")
                    if verbose:
                        print(f"[{self.agent_id}] [{target_server}] {tool_name} {tool_args}")
                    try:
                        result = await self.sessions[target_server].call_tool(tool_name, tool_args)
                        result_content = result.content
                        if not isinstance(result_content, str):
                            result_content = str(result_content)
                        packed = json.dumps(result_content)
                        packed = _cap_tool_json_payload(packed, TOOL_RESULT_MAX_TOKENS)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": packed,
                        })
                        # ❌ Do NOT save tool messages - only keep in memory for current conversation
                    except Exception as e:
                        err = json.dumps({"error": str(e)})
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id, "name": tool_name, "content": err,
                        })
            except Exception as e:
                final_chunks.append(f"Error: {e}")
                # Save error message as final answer
                error_message = f"Error: {e}"
                if persist_history:
                    await self.session_manager.add_message("assistant", error_message)
                hit_iteration_limit = False
                break

        if hit_iteration_limit:
            warning_message = "\n  Reached maximum iterations. Please simplify your query."
            final_chunks.append(warning_message)
            # Save warning as final answer
            final_answer = "\n".join(c for c in final_chunks if c).strip()
            if final_answer and persist_history:
                await self.session_manager.add_message("assistant", final_answer)
        
        return "\n".join(c for c in final_chunks if c).strip()

    async def cleanup(self) -> None:
        """Release MCP connections."""
        await self.exit_stack.aclose()
