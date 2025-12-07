import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env


class MCPClient:
    def __init__(self):
        # MCP session
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()

        # OpenAI client (dùng OPENAI_API_KEY trong .env)
        self.openai = OpenAI()

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server

        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        # Check if there's a virtual environment in the same directory as the script
        # If so, use Python from that venv to ensure correct dependencies
        script_path = Path(server_script_path).resolve()
        script_dir = script_path.parent
        
        if is_python:
            # Look for common venv directory names
            venv_dirs = [".venv", "venv", "env"]
            python_executable = None
            
            for venv_dir in venv_dirs:
                venv_path = script_dir / venv_dir
                if venv_path.exists() and venv_path.is_dir():
                    # Determine the Python executable path based on OS
                    if sys.platform == "win32":
                        python_exe = venv_path / "Scripts" / "python.exe"
                    else:
                        python_exe = venv_path / "bin" / "python"
                    
                    if python_exe.exists():
                        python_executable = str(python_exe)
                        break
            
            if python_executable:
                # Use Python from venv
                command = python_executable
                args = [str(script_path)]
                print(f"Using Python from venv: {python_executable}")
            else:
                # Fallback to system python
                command = "python"
                args = [server_script_path]
                print(f"Using system Python: {command}")
        else:
            # For JavaScript, use node directly
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
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def process_query(self, query: str) -> str:
        """Process a query using OpenAI and available MCP tools"""
        if self.session is None:
            raise RuntimeError("MCP session is not initialized")

        messages = [
            {
                "role": "user",
                "content": query,
            }
        ]

        response = await self.session.list_tools()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            }
            for tool in response.tools
        ]

        final_text_chunks = []

        while True:
            completion = self.openai.chat.completions.create(
                model="gpt-4o-mini",  # em có thể đổi sang gpt-4.1 / gpt-4.1-mini / gpt-4o tuỳ
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            message = completion.choices[0].message
            content_text = message.content or ""
            if content_text:
                final_text_chunks.append(content_text)

            tool_calls = message.tool_calls or []

            if not tool_calls:
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

            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_args = {}

                result = await self.session.call_tool(tool_name, tool_args)

                # Kiểm tra và chuyển kết quả của tool thành chuỗi nếu cần thiết
                result_content = result.content

                # Đảm bảo result_content là chuỗi, nếu không chuyển thành chuỗi
                if not isinstance(result_content, str):
                    result_content = str(result_content)

                final_text_chunks.append(f"[Calling tool {tool_name} with args {tool_args}]")
                final_text_chunks.append(str(result_content))  # Đảm bảo là chuỗi

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tool_name,
                        "content": json.dumps(result_content),  # Chuyển kết quả thành chuỗi JSON
                    }
                )

        return "\n".join(chunk for chunk in final_text_chunks if chunk)

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == "quit":
                    break

                response = await self.process_query(query)
                print("\n" + response)

            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
