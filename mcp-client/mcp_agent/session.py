"""Session management backed by Postgres."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


class SessionManager:
    """Manages chat history stored in Postgres."""

    def __init__(self, db_pool: Any, user_id: str):
        if db_pool is None:
            raise ValueError("db_pool is required for Postgres-backed sessions")
        self._pool = db_pool
        self._user_id = (user_id or "anonymous").strip() or "anonymous"
        self.current_session_id: Optional[str] = None

    async def create_session(self, session_name: Optional[str] = None, project_id: Optional[int] = None) -> str:
        """Create a new session and persist to Postgres."""
        session_id = str(uuid.uuid4())[:8]
        session_data = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "session_name": session_name or f"Session {session_id}",
            "messages": [],
            "project_id": project_id,
        }
        await self._save_session(session_id, session_data, project_id=project_id)
        self.current_session_id = session_id
        return session_id

    async def load_session(self, session_id: str) -> bool:
        """Load session by id for this user."""
        data = await self._get_session(session_id)
        if not data:
            return False
        self.current_session_id = session_id
        return True

    async def list_sessions(self, project_id: Optional[int] = None, unassigned_only: bool = False) -> List[Dict[str, Any]]:
        """List all sessions for this user.

        Args:
            project_id: If provided, only sessions for that project are returned.
            unassigned_only: If True, only return sessions where project_id IS NULL.
                           If False and project_id is None, return all sessions.
        """
        if unassigned_only:
            # Only sessions without project (project_id IS NULL)
            rows = await self._pool.fetch(
                "SELECT id, content, project_id FROM session WHERE user_id = $1 AND project_id IS NULL "
                "ORDER BY content->>'created_at' DESC",
                self._user_id,
            )
        elif project_id is not None:
            # Specific project
            rows = await self._pool.fetch(
                "SELECT id, content, project_id FROM session WHERE user_id = $1 AND project_id = $2 "
                "ORDER BY content->>'created_at' DESC",
                self._user_id,
                project_id,
            )
        else:
            # All sessions
            rows = await self._pool.fetch(
                "SELECT id, content, project_id FROM session WHERE user_id = $1 ORDER BY content->>'created_at' DESC",
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
            sessions.append(
                {
                    "session_id": data.get("session_id") or row["id"],
                    "session_name": data.get("session_name", ""),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "project_id": data.get("project_id") or row.get("project_id"),
                }
            )
        return sessions

    async def get_current_messages(self) -> List[Dict[str, Any]]:
        """Get messages from current session."""
        if not self.current_session_id:
            return []
        data = await self._get_session(self.current_session_id)
        if not data:
            return []
        return data.get("messages", [])

    async def add_message(self, role: str, content: str, tool_calls: Optional[List] = None):
        """Add a message to the current session."""
        if not self.current_session_id:
            return
        data = await self._get_session(self.current_session_id)
        if not data:
            data = {
                "session_id": self.current_session_id,
                "created_at": datetime.now().isoformat(),
                "messages": [],
            }

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        data["messages"].append(message)
        data["updated_at"] = datetime.now().isoformat()
        await self._save_session(self.current_session_id, data)

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

    async def _get_session(self, session_id: str) -> Dict[str, Any] | None:
        row = await self._pool.fetchrow(
            "SELECT content FROM session WHERE id = $1 AND user_id = $2",
            session_id,
            self._user_id,
        )
        if not row:
            return None
        content = row["content"]
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None
        return content

    async def _save_session(self, session_id: str, content: Dict[str, Any], project_id: Optional[int] = None) -> None:
        await self._pool.execute(
            """
            INSERT INTO session (id, user_id, content, project_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id)
            DO UPDATE SET content = EXCLUDED.content, user_id = EXCLUDED.user_id, project_id = EXCLUDED.project_id
            """,
            session_id,
            self._user_id,
            json.dumps(content),
            project_id,
        )
