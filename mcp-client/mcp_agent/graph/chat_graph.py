"""Outer chat graph (Cách A): MessagesState + checkpoint, Orchestrator as one node.

Uses the same AsyncPostgresSaver / MemorySaver as workflow graphs but isolates storage with
``checkpoint_ns="chat"`` so thread_id=session_id does not collide with mutation/create_table checkpoints.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langmem.short_term import RunningSummary, SummarizationNode
from typing_extensions import NotRequired

logger = logging.getLogger(__name__)

# Namespace for chat checkpoints — keep distinct from default (workflow) namespace.
CHAT_CHECKPOINT_NS = "chat"
# Summarization tuning for summary + recent turns routing (.env configurable).
SUMMARY_MODEL_MAX_TOKENS = max(32, int(os.getenv("CHAT_SUMMARY_MODEL_MAX_TOKENS", "96")))
SUMMARY_TRIGGER_TOKENS = max(128, int(os.getenv("CHAT_SUMMARY_TRIGGER_TOKENS", "384")))
SUMMARY_INPUT_MAX_TOKENS = max(128, int(os.getenv("CHAT_SUMMARY_INPUT_MAX_TOKENS", "384")))
SUMMARY_MAX_TOKENS = max(32, int(os.getenv("CHAT_SUMMARY_MAX_TOKENS", "96")))
CHAT_HISTORY_HARD_CAP_TOKENS = max(4096, int(os.getenv("CHAT_HISTORY_HARD_CAP_TOKENS", "20000")))


class ChatGraphState(MessagesState, total=False):
    """Messages from user/assistant turns plus last orchestration result metadata."""

    context: NotRequired[Dict[str, RunningSummary]]
    summarized_messages: NotRequired[List[BaseMessage]]
    response: NotRequired[str]
    agent_id: NotRequired[str]
    pending_workflow_resume: NotRequired[bool]
    tool_events: NotRequired[List[Dict[str, Any]]]
    workflow_state: NotRequired[Dict[str, Any]]
    intent: NotRequired[Dict[str, Any]]
    success: NotRequired[bool]
    # Project / user scoping — set per-invocation by chat_usecase, persisted in checkpoint
    project_id: NotRequired[Optional[str]]
    user_id: NotRequired[Optional[str]]
    allowed_db_uri: NotRequired[Optional[str]]
    # Optional: an IntentResult dict already classified by the caller
    # (e.g. chat_usecase running its share-permission gate). Skips a
    # duplicate LLM call inside the orchestrator's _parse_intent_node.
    pre_classified_intent: NotRequired[Optional[Dict[str, Any]]]


def chat_checkpoint_config(session_id: str) -> Dict[str, Any]:
    return {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": CHAT_CHECKPOINT_NS,
        }
    }


def _messages_to_llm_override_dicts(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    """Convert LangChain messages to SessionManager-style dicts (user/assistant only)."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": _text_content(m.content)})
        elif isinstance(m, AIMessage):
            out.append({"role": "assistant", "content": _text_content(m.content)})
    return out


def _text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def langchain_messages_to_session_rows(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    """Persistable rows for session.content.messages (UI)."""
    ts = datetime.now().isoformat()
    rows: List[Dict[str, Any]] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            rows.append({"role": "user", "content": _text_content(m.content), "timestamp": ts})
        elif isinstance(m, AIMessage):
            rows.append({"role": "assistant", "content": _text_content(m.content), "timestamp": ts})
    return rows


def _last_user_text(messages: Sequence[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return _text_content(m.content)
    return ""


def _running_summary_text(context: Any) -> str:
    if not isinstance(context, dict):
        return ""
    item = context.get("running_summary")
    if item is None:
        return ""
    summary = getattr(item, "summary", "")
    return str(summary or "").strip()


def _truncate_messages_token_budget(messages: Sequence[BaseMessage], max_tokens: int) -> List[BaseMessage]:
    """Drop oldest messages until the thread fits within an approximate token budget."""
    msgs = list(messages)
    while len(msgs) > 1:
        total = sum(count_tokens_approximately(_text_content(m.content)) for m in msgs)
        if total <= max_tokens:
            return msgs
        msgs.pop(0)
    return msgs


def build_chat_graph(orchestrator: Any, checkpointer: Any):
    """Compile chat graph: ingest → maybe_summarize → orchestrate."""
    summarization_model = init_chat_model(
        orchestrator._router_model,
        model_provider="openai",
    ).bind(max_tokens=SUMMARY_MODEL_MAX_TOKENS)
    summarization_node = SummarizationNode(
        token_counter=count_tokens_approximately,
        model=summarization_model,
        max_tokens=SUMMARY_INPUT_MAX_TOKENS,
        max_tokens_before_summary=SUMMARY_TRIGGER_TOKENS,
        max_summary_tokens=SUMMARY_MAX_TOKENS,
    )

    async def ingest_user(state: ChatGraphState) -> Dict[str, Any]:
        return {}

    async def orchestrate_node(state: ChatGraphState) -> Dict[str, Any]:
        session_id = orchestrator.session_manager.current_session_id
        if not session_id:
            logger.warning("[ChatGraph] No current_session_id on session_manager")
            return {
                "messages": [AIMessage(content="Error: no active session.")],
                "response": "Error: no active session.",
                "agent_id": "unknown",
                "pending_workflow_resume": False,
                "tool_events": [],
                "workflow_state": {},
                "intent": {},
                "success": False,
            }

        msgs = list(state.get("messages") or [])
        summarized = list(state.get("summarized_messages") or [])
        summary_text = _running_summary_text(state.get("context"))
        trimmed = _truncate_messages_token_budget(msgs, CHAT_HISTORY_HARD_CAP_TOKENS)
        intent_msgs = summarized or trimmed
        # Summarization snapshots can occasionally lag one turn behind and miss
        # the newest HumanMessage. Fallback to trimmed live messages before
        # concluding the user input is empty.
        query = _last_user_text(intent_msgs) or _last_user_text(trimmed)
        if not query.strip():
            return {
                "messages": [AIMessage(content="Error: empty user message.")],
                "response": "Error: empty user message.",
                "agent_id": "unknown",
                "pending_workflow_resume": False,
                "tool_events": [],
                "workflow_state": {},
                "intent": {},
                "success": False,
            }

        override = _messages_to_llm_override_dicts(intent_msgs)
        orchestrator.session_manager.set_llm_context_override(override)
        try:
            result = await orchestrator.process_query(
                query,
                session_id=session_id,
                conversation_context=override,
                conversation_summary=summary_text,
                project_id=state.get("project_id"),
                user_id=state.get("user_id"),
                allowed_db_uri=state.get("allowed_db_uri"),
                pre_classified_intent=state.get("pre_classified_intent"),
            )
        except Exception as e:
            logger.exception("[ChatGraph] orchestrate_node: %s", e)
            return {
                "messages": [AIMessage(content=f"Error: {e}")],
                "response": f"Error: {e}",
                "agent_id": "unknown",
                "pending_workflow_resume": False,
                "tool_events": [],
                "workflow_state": {},
                "intent": {},
                "success": False,
            }
        finally:
            orchestrator.session_manager.clear_llm_context_override()

        if not isinstance(result, dict):
            text = str(result)
            return {
                "messages": [AIMessage(content=text)],
                "response": text,
                "agent_id": "unknown",
                "pending_workflow_resume": False,
                "tool_events": [],
                "workflow_state": {},
                "intent": {},
                "success": True,
            }

        response_text = str(result.get("response", ""))
        workflow_state = result.get("workflow_state") if isinstance(result.get("workflow_state"), dict) else {}
        success = True
        if isinstance(workflow_state, dict):
            success = bool(workflow_state.get("success", True))
            out = workflow_state.get("output") or {}
            if isinstance(out, dict) and out.get("type") in {"error", "needs_input"}:
                success = False

        return {
            "messages": [AIMessage(content=response_text)],
            "response": response_text,
            "agent_id": str(result.get("agent_id", "unknown")),
            "pending_workflow_resume": bool(result.get("pending_workflow_resume") or result.get("requires_approval")),
            "tool_events": result.get("tool_events") if isinstance(result.get("tool_events"), list) else [],
            "workflow_state": workflow_state,
            "intent": result.get("intent") if isinstance(result.get("intent"), dict) else {},
            "success": success,
        }

    graph = StateGraph(ChatGraphState)
    graph.add_node("ingest_user", ingest_user)
    graph.add_node("summarize", summarization_node)
    graph.add_node("orchestrate", orchestrate_node)
    graph.add_edge(START, "ingest_user")
    graph.add_edge("ingest_user", "summarize")
    graph.add_edge("summarize", "orchestrate")
    graph.add_edge("orchestrate", END)

    return graph.compile(checkpointer=checkpointer)
