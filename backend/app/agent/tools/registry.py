"""Registry tool in-process → sinh schema OpenAI function-calling.

The LLM "sees" tools via the openai_schemas() array; the connection param is NOT in the schema
(the tool reads it from the ContextVar) so the LLM never sees the DSN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

ToolFn = Callable[..., Awaitable]


@dataclass
class ToolOutput:
    """Return this (instead of a plain ``str``) to split what the model sees from what the
    frontend gets. ``summary`` is fed back into the tool loop as the tool message — keep it
    SMALL (a confirmation, never the data). ``payload`` is the full result shipped to the FE
    as a tool event and persisted. Used by generate_chart so the chart DATA never bloats the
    message loop (the model only needs to know the chart was built, not see every row)."""
    summary: str
    payload: str


@dataclass
class ToolSpec:
    name: str
    fn: ToolFn
    schema: dict
    write: bool = False  # True if the tool can modify data (gated at workflow/approval)


_REGISTRY: dict[str, ToolSpec] = {}


def tool(description: str, parameters: dict, *, write: bool = False, name: str | None = None):
    """Register an async function as a tool. `parameters` is the JSON Schema for the args the LLM generates."""

    def deco(fn: ToolFn) -> ToolFn:
        nm = name or fn.__name__
        _REGISTRY[nm] = ToolSpec(
            name=nm,
            fn=fn,
            schema={
                "type": "function",
                "function": {"name": nm, "description": description, "parameters": parameters},
            },
            write=write,
        )
        return fn

    return deco


def get(name: str) -> ToolSpec:
    return _REGISTRY[name]


def has(name: str) -> bool:
    return name in _REGISTRY


def openai_schemas(names: list[str] | None = None) -> list[dict]:
    if names is None:
        return [s.schema for s in _REGISTRY.values()]
    return [_REGISTRY[n].schema for n in names if n in _REGISTRY]


def all_names() -> list[str]:
    return list(_REGISTRY.keys())
