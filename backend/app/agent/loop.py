"""Per-request tool loop — does NOT keep state on the instance.

Everything (system prompt, history, backends) is passed in; so a single singleton
orchestrator can serve many concurrent users without mixing data.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, cast

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
    exhausted: bool = False  # True if the loop hit max_tool_iterations while still calling tools


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
    final_text = ""
    exhausted = False

    for _ in range(s.max_tool_iterations):
        completion = await client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            tools=cast(Any, tools if tools else None),
            tool_choice="auto",
            temperature=0.1,
        )
        msg = completion.choices[0].message
        # The SDK union now includes a "custom" tool-call variant (no .function); we only ever
        # register function tools, so keep just those — this also narrows the type for pyright.
        tool_calls = [tc for tc in (msg.tool_calls or []) if tc.type == "function"]
        if not tool_calls:
            # No tool call → this turn IS the final answer. Use only its text (interim narration
            # emitted alongside tool calls is kept in `messages` for context, not in the reply).
            final_text = msg.content or ""
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
                    "content": content,
                }
            )
    else:
        # Loop ran out of iterations while the model still wanted tools (no `break`). The last
        # tool results are already in `messages`; force ONE final, tool-free turn so the model
        # MUST produce an answer from them instead of leaving the reply empty/truncated.
        exhausted = True
        logger.warning("tool loop hit max_tool_iterations (%d) — forcing a final answer",
                       s.max_tool_iterations)
        completion = await client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            temperature=0.1,
        )
        final_text = completion.choices[0].message.content or ""

    return LoopResult(text=final_text.strip(), tool_events=events, exhausted=exhausted)
