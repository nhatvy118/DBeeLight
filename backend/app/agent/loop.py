"""Per-request tool loop — does NOT keep state on the instance.

Everything (system prompt, history, backends) is passed in; so a single singleton
orchestrator can serve many concurrent users without mixing data.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.agent.llm import get_llm
from app.agent.tools.backends import ToolBackend
from app.config import get_settings

logger = logging.getLogger("agent.loop")


@dataclass
class ToolEvent:
    tool: str
    args: dict
    result: str
    is_error: bool = False


@dataclass
class LoopResult:
    text: str
    tool_events: list[ToolEvent] = field(default_factory=list)


def _cap(text: str, max_tokens: int) -> str:
    # ~4 chars / token
    limit = max(500, max_tokens * 4)
    return text if len(text) <= limit else text[:limit] + "\n...[tool output truncated]"


async def run_tool_loop(
    *,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    backends: list[ToolBackend],
    model: str | None = None,
) -> LoopResult:
    s = get_settings()
    model = model or s.llm_model
    client = get_llm()

    tools: list[dict] = []
    for b in backends:
        tools.extend(b.list_tools_openai())

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in history:
        role = m.get("role")
        if role in ("user", "assistant") and m.get("content"):
            messages.append({"role": role, "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    events: list[ToolEvent] = []
    chunks: list[str] = []

    for _ in range(s.max_tool_iterations):
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto",
            temperature=0.1,
        )
        msg = completion.choices[0].message
        if msg.content:
            chunks.append(msg.content)
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            break

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            backend = next((b for b in backends if b.owns(name)), None)
            if backend is None:
                content = json.dumps({"error": f"Tool '{name}' does not exist"})
                is_err = True
            else:
                res = await backend.call_tool(name, args)
                content = res.content
                is_err = res.is_error
            events.append(ToolEvent(tool=name, args=args, result=content, is_error=is_err))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": _cap(content, s.tool_result_max_tokens),
                }
            )

    return LoopResult(text="\n".join(c for c in chunks if c).strip(), tool_events=events)
