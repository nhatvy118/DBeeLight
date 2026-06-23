"""Stream graph execution node-by-node, emitting a user-facing 'stage' per node.

Stages come straight from the LangGraph nodes (the single source of progress truth) — not
from orchestration-level steps.

``stream_mode=["debug", "values"]`` is used so the stage fires ON NODE ENTRY, not on
completion: the ``debug`` stream emits a ``{"type": "task", ...}`` event right BEFORE a node
runs (and ``task_result`` after), while ``values`` carries the full state after each step (to
return as the final state). Emitting on entry means a slow node (e.g. an LLM call) shows its
"…in progress" label immediately instead of only once it finishes.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agent.graph.state import STAGE_LABELS

StageCb = Callable[[str], Awaitable[None]]


async def stream_stages(
    graph: Any,
    graph_input: Any,
    on_stage: StageCb | None,
    config: RunnableConfig | None = None,
) -> dict | None:
    """Drive ``graph`` via astream, emitting a stage the moment each labelled node STARTS.

    Returns the last full state snapshot (``values`` mode). Callers that use a checkpointer
    (interrupt workflows) still read ``aget_state`` afterwards for the pending/next flag.
    """
    final: dict | None = None
    async for mode, chunk in graph.astream(graph_input, config, stream_mode=["debug", "values"]):
        if mode == "debug":
            # 'task' fires BEFORE the node body runs; 'task_result' after — we only want entry.
            if chunk.get("type") != "task":
                continue
            node = (chunk.get("payload") or {}).get("name") or ""
            if node.startswith("__"):  # internal markers (__start__/__interrupt__/…)
                continue
            label = STAGE_LABELS.get(node)
            if label and on_stage is not None:
                await on_stage(label)
        elif mode == "values":
            final = chunk
    return final
