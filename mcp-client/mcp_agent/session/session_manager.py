"""Session management backed by Postgres with Redis stack for batch writes."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

# Optional: OpenAI for AI-generated session name summary
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore

# Try to import Redis stack functions (optional dependency)
# Note: This import will work when running from api-server context
# If not available, fallback to direct DB writes
REDIS_STACK_AVAILABLE = False
try:
    import sys
    import os
    # Try to add api-server to path if not already there
    # api_server_path = os.path.join(os.path.dirname(__file__), "..", "..", "api-server")
    # if os.path.exists(api_server_path) and api_server_path not in sys.path:
    #     sys.path.insert(0, api_server_path)
    
    from internal.utils.redis_client import (
        redis_stack_push,
        redis_stack_get_all,
        redis_stack_length,
        redis_stack_clear,
    )
    REDIS_STACK_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    REDIS_STACK_AVAILABLE = False
    # Fallback functions if Redis not available
    async def redis_stack_push(*args, **kwargs):
        return False
    async def redis_stack_get_all(*args, **kwargs):
        return []
    async def redis_stack_length(*args, **kwargs):
        return 0
    async def redis_stack_clear(*args, **kwargs):
        return False


class SessionManager:
    """Manages chat history stored in Postgres with Redis stack for batch writes."""

    def __init__(
        self,
        db_pool: Any,
        user_id: str,
        *,
        summarize_model: Optional[str] = None,
    ):
        self._user_id = (user_id or "anonymous").strip() or "anonymous"
        self.current_session_id: Optional[str] = None
        self._memory: Dict[str, Dict[str, Any]] = {}  # guest only: no DB
        self._batch_size = 20  # Flush to DB when stack reaches this size
        self._summarize_model = summarize_model
        self._openai: Optional[Any] = None
        if summarize_model and AsyncOpenAI is not None:
            self._openai = AsyncOpenAI()
        if self._user_id == "anonymous":
            self._pool = None  # guest: session in-memory, reload = new session
        else:
            if db_pool is None:
                raise ValueError("db_pool is required for Postgres-backed sessions")
            self._pool = db_pool
    
    def _get_stack_key(self, session_id: str) -> str:
        """Get Redis stack key for a session: {user_id}:{session_id}:stack"""
        return f"{self._user_id}:{session_id}:stack"

    @staticmethod
    def _message_summary(text: str, max_len: int = 50) -> str:
        """Fallback: truncate message for session name (no AI)."""
        s = (text or "").strip().replace("\n", " ")
        if not s:
            return "New chat"
        return (s[: max_len - 3].rstrip() + "...") if len(s) > max_len else s

    async def _summarize_for_session_name(self, text: str) -> str:
        """Generate short session title from first message (AI if available, else truncate)."""
        s = (text or "").strip()
        if not s:
            return "New chat"
        if self._openai and self._summarize_model:
            try:
                response = await self._openai.chat.completions.create(
                    model=self._summarize_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Reply with a very short chat title (max 6–8 words) for the user message. No quotes, no punctuation at the end.",
                        },
                        {"role": "user", "content": s[:2000]},
                    ],
                    max_tokens=30,
                    temperature=0.3,
                )
                content = (response.choices[0].message.content or "").strip()
                if content:
                    return content[:80]
            except Exception:
                pass
        return self._message_summary(text)

    async def update_session_name(self, session_id: str, session_name: str) -> None:
        """Update only the session_name column (and in-memory for guest)."""
        if self._pool is None:
            if session_id in self._memory:
                self._memory[session_id]["session_name"] = session_name or ""
            return
        await self._pool.execute(
            "UPDATE session SET session_name = $1 WHERE id = $2 AND user_id = $3",
            session_name or "",
            session_id,
            self._user_id,
        )

    async def create_session(self, session_name: Optional[str] = None, project_id: Optional[str] = None) -> str:
        """Create a new session and persist to Postgres. project_id is UUID string (references projects.id)."""
        session_id = str(uuid.uuid4())[:8]
        name = (session_name or "").strip() or "New chat"
        session_data = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "messages": [],
            "project_id": project_id,
        }
        await self._save_session(session_id, session_data, project_id=project_id, session_name=name)
        self.current_session_id = session_id
        return session_id

    async def load_session(self, session_id: str) -> bool:
        """Load session by id for this user."""
        data = await self._get_session(session_id)
        if not data:
            return False
        self.current_session_id = session_id
        return True

    async def list_sessions(self, project_id: Optional[str] = None, unassigned_only: bool = False) -> List[Dict[str, Any]]:
        """List all sessions for this user (DB or in-memory for guest)."""
        if self._pool is None:
            out: List[Dict[str, Any]] = []
            for sid, data in self._memory.items():
                pid = data.get("project_id")
                if unassigned_only and pid is not None:
                    continue
                if project_id is not None and pid != project_id:
                    continue
                out.append({
                    "session_id": data.get("session_id") or sid,
                    "session_name": data.get("session_name", ""),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "project_id": pid,
                })
            out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
            return out
        if unassigned_only:
            rows = await self._pool.fetch(
                "SELECT id, content, project_id, session_name FROM session WHERE user_id = $1 AND project_id IS NULL "
                "ORDER BY content->>'created_at' DESC",
                self._user_id,
            )
        elif project_id is not None:
            # Specific project (project_id is UUID)
            rows = await self._pool.fetch(
                "SELECT id, content, project_id, session_name FROM session WHERE user_id = $1 AND project_id = $2::uuid "
                "ORDER BY content->>'created_at' DESC",
                self._user_id,
                project_id,
            )
        else:
            # All sessions
            rows = await self._pool.fetch(
                "SELECT id, content, project_id, session_name FROM session WHERE user_id = $1 ORDER BY content->>'created_at' DESC",
                self._user_id,
            )
        sessions: List[Dict[str, Any]] = []
        for row in rows:
            data = row["content"] or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    continue
            if not isinstance(data, dict):
                continue
            # session_name from column only; if null/empty use "New chat"
            name = (row.get("session_name") or "").strip() or "New chat"
            sessions.append(
                {
                    "session_id": data.get("session_id") or row["id"],
                    "session_name": name,
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "project_id": data.get("project_id") or row.get("project_id"),
                }
            )
        return sessions

    async def flush_current_session(self) -> None:
        """Flush current session Redis stack to DB so history survives reload/restart."""
        if not self.current_session_id:
            return
        await self._flush_stack_to_db(self.current_session_id)

    async def get_current_messages(self) -> List[Dict[str, Any]]:
        """
        Get messages from current session.
        Combines messages from Redis stack + DB.
        Only returns 'user' and 'assistant' messages, filters out 'tool' messages.
        """
        if not self.current_session_id:
            return []

        all_messages: List[Dict[str, Any]] = []

        # Get messages from DB
        data = await self._get_session(self.current_session_id)
        if data:
            all_messages.extend(data.get("messages", []))

        # Get messages from Redis stack (if available)
        if self._pool is not None and REDIS_STACK_AVAILABLE:
            stack_key = self._get_stack_key(self.current_session_id)
            stack_messages = await redis_stack_get_all(stack_key)
            all_messages.extend(stack_messages)

        # Filter out tool messages, only keep user and assistant
        return [msg for msg in all_messages if msg.get("role") in ("user", "assistant")]

    async def add_message(self, role: str, content: str, tool_calls: Optional[List] = None):
        """
        Add a message to the current session using Redis stack.
        Only saves 'user' and 'assistant' messages, not 'tool' messages.
        When stack reaches batch_size (20), automatically flushes to DB.
        """
        if not self.current_session_id:
            return
        
        # Only save user and assistant messages, skip tool messages
        if role not in ("user", "assistant"):
            return
        
        # Don't save assistant messages with empty content (only tool_calls, no text)
        if role == "assistant" and not content.strip():
            return
        
        # Session name = summary of first user message
        is_first_user_message = False
        if role == "user" and content.strip():
            current = await self.get_current_messages()
            user_count = sum(1 for m in current if m.get("role") == "user")
            is_first_user_message = user_count == 0
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        
        # For guest users (no DB), use in-memory storage
        if self._pool is None:
            if self.current_session_id not in self._memory:
                self._memory[self.current_session_id] = {
                    "session_id": self.current_session_id,
                    "created_at": datetime.now().isoformat(),
                    "messages": [],
                    "session_name": "",
                }
            self._memory[self.current_session_id]["messages"].append(message)
            self._memory[self.current_session_id]["updated_at"] = datetime.now().isoformat()
            if is_first_user_message:
                summary = await self._summarize_for_session_name(content)
                await self.update_session_name(self.current_session_id, summary)
            return
        
        # For authenticated users: push to Redis stack
        stack_key = self._get_stack_key(self.current_session_id)
        
        if REDIS_STACK_AVAILABLE:
            # Push message to Redis stack
            await redis_stack_push(stack_key, message)
            if is_first_user_message:
                summary = await self._summarize_for_session_name(content)
                await self.update_session_name(self.current_session_id, summary)
            # Check if we need to flush to DB
            stack_length = await redis_stack_length(stack_key)
            if stack_length >= self._batch_size:
                await self._flush_stack_to_db(self.current_session_id)
        else:
            # Fallback: direct write to DB (old behavior)
            data = await self._get_session(self.current_session_id)
            if not data:
                data = {
                    "session_id": self.current_session_id,
                    "created_at": datetime.now().isoformat(),
                    "messages": [],
                }
            data["messages"].append(message)
            data["updated_at"] = datetime.now().isoformat()
            session_name = data.pop("session_name", None)
            if is_first_user_message and content.strip():
                session_name = await self._summarize_for_session_name(content)
            await self._save_session(
                self.current_session_id, data, session_name=session_name
            )

    async def get_session_info(self) -> Dict[str, Any]:
        """Get current session information."""
        if not self.current_session_id:
            return {}
        data = await self._get_session(self.current_session_id)
        if not data:
            return {}
        return {
            "session_id": data.get("session_id", ""),
            "session_name": data.get("session_name", ""),
            "created_at": data.get("created_at", ""),
            "message_count": len(data.get("messages", [])),
            "project_id": data.get("project_id"),
        }

    async def replace_latest_assistant_message(self, old_content: str, new_content: str) -> bool:
        """Replace the latest assistant message content in the current session.

        This is used when a response is first persisted by the agent loop and
        later enriched with internal markers (for example SQL action ids) that
        must also survive page reload/history fetch.
        """
        if not self.current_session_id:
            return False
        if not (old_content or "").strip() or not (new_content or "").strip():
            return False

        await self.flush_current_session()
        data = await self._get_session(self.current_session_id)
        if not data:
            return False

        messages = data.get("messages", [])
        if not isinstance(messages, list):
            return False

        replaced = False
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            if str(msg.get("content", "")) != old_content:
                continue
            msg["content"] = new_content
            replaced = True
            break

        if not replaced:
            return False

        data["updated_at"] = datetime.now().isoformat()
        session_name = data.pop("session_name", None)
        await self._save_session(self.current_session_id, data, session_name=session_name)
        return True

    async def set_pending_approval(self, session_id: str, payload: Dict[str, Any]) -> None:
        """Persist pending approval payload into session content."""
        if not session_id:
            return
        data = await self._get_session(session_id)
        if not data:
            return
        data["pending_approval"] = payload
        data["updated_at"] = datetime.now().isoformat()
        session_name = data.pop("session_name", None)
        await self._save_session(session_id, data, session_name=session_name)

    async def get_pending_approval(self, session_id: str) -> Dict[str, Any] | None:
        """Read pending approval payload from session content."""
        if not session_id:
            return None
        data = await self._get_session(session_id)
        if not data:
            return None
        pending = data.get("pending_approval")
        return pending if isinstance(pending, dict) else None

    async def clear_pending_approval(self, session_id: str) -> None:
        """Clear pending approval payload from session content."""
        if not session_id:
            return
        data = await self._get_session(session_id)
        if not data:
            return
        if "pending_approval" in data:
            data.pop("pending_approval", None)
            data["updated_at"] = datetime.now().isoformat()
            session_name = data.pop("session_name", None)
            await self._save_session(session_id, data, session_name=session_name)

    async def set_sql_action_state(self, session_id: str, action_id: str, state: str) -> None:
        """Persist SQL action state for a preview action_id (pending/executed/cancelled)."""
        if not session_id or not (action_id or "").strip():
            return
        data = await self._get_session(session_id)
        if not data:
            return
        states = data.get("sql_action_states")
        if not isinstance(states, dict):
            states = {}
        states[action_id.strip()] = state
        data["sql_action_states"] = states
        data["updated_at"] = datetime.now().isoformat()
        session_name = data.pop("session_name", None)
        await self._save_session(session_id, data, session_name=session_name)

    async def get_sql_action_state(self, session_id: str, action_id: str) -> str | None:
        """Get persisted SQL action state for a preview action_id."""
        if not session_id or not (action_id or "").strip():
            return None
        data = await self._get_session(session_id)
        if not data:
            return None
        states = data.get("sql_action_states")
        if not isinstance(states, dict):
            return None
        value = states.get(action_id.strip())
        return str(value) if value is not None else None

    async def get_sql_action_states(self, session_id: str) -> Dict[str, str]:
        """Get all persisted SQL action states for a session."""
        if not session_id:
            return {}
        data = await self._get_session(session_id)
        if not data:
            return {}
        states = data.get("sql_action_states")
        if not isinstance(states, dict):
            return {}
        out: Dict[str, str] = {}
        for k, v in states.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
        return out

    async def _get_session(self, session_id: str) -> Dict[str, Any] | None:
        if self._pool is None:
            return self._memory.get(session_id)
        row = await self._pool.fetchrow(
            "SELECT content, session_name FROM session WHERE id = $1 AND user_id = $2",
            session_id,
            self._user_id,
        )
        if not row:
            return None
        content = row["content"]
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                return None
        else:
            data = dict(content)
        # session_name from column only; if null/empty use "New chat"
        data["session_name"] = (row.get("session_name") or "").strip() or "New chat"
        return data

    async def _flush_stack_to_db(self, session_id: str) -> None:
        """
        Flush messages from Redis stack to DB in batch.
        Merges stack messages with existing DB messages.
        """
        if not REDIS_STACK_AVAILABLE or self._pool is None:
            return
        
        stack_key = self._get_stack_key(session_id)
        stack_messages = await redis_stack_get_all(stack_key)
        
        if not stack_messages:
            return
        
        # Get existing session data from DB
        data = await self._get_session(session_id)
        if not data:
            data = {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "messages": [],
            }
        
        # Merge: existing DB messages + new stack messages
        data["messages"].extend(stack_messages)
        data["updated_at"] = datetime.now().isoformat()
        
        # session_name is separate (column); pass as param, don't include in content
        session_name = data.pop("session_name", None)
        await self._save_session(session_id, data, session_name=session_name)
        
        # Clear Redis stack after successful flush
        await redis_stack_clear(stack_key)
    
    async def _save_session(
        self,
        session_id: str,
        content: Dict[str, Any],
        project_id: Optional[str] = None,
        session_name: Optional[str] = None,
    ) -> None:
        if self._pool is None:
            # Guest: store merged view in memory so get_session_info / list_sessions work
            self._memory[session_id] = {**content, "session_name": session_name or ""}
            return
        await self._pool.execute(
            """
            INSERT INTO session (id, user_id, content, project_id, session_name)
            VALUES ($1, $2, $3, $4::uuid, $5)
            ON CONFLICT (id)
            DO UPDATE SET
                content = EXCLUDED.content,
                user_id = EXCLUDED.user_id,
                project_id = COALESCE(EXCLUDED.project_id, session.project_id),
                session_name = COALESCE(EXCLUDED.session_name, session.session_name)
            """,
            session_id,
            self._user_id,
            json.dumps(content),
            project_id,
            session_name,
        )
