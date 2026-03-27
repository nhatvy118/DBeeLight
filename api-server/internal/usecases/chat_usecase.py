from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from fastapi import HTTPException

from internal.repositories.agent_repository import AgentRepository
from internal.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class ChatUseCase:
    def __init__(self, agent_repo: AgentRepository, project_repo: Optional[ProjectRepository] = None):
        self._agent_repo = agent_repo
        self._project_repo = project_repo

    @staticmethod
    def _extract_last_mutation_sql_block(text: str) -> str | None:
        matches = re.findall(r"```sql([\s\S]*?)```", text or "", flags=re.IGNORECASE)
        if not matches:
            return None
        last = (matches[-1] or "").strip()
        if not last:
            return None
        first_token = (last.split()[:1] or [""])[0].upper()
        if first_token in {"SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH", "PRAGMA"}:
            return None
        return last

    @staticmethod
    def _attach_sql_action_id_marker(text: str, action_id: str) -> str:
        return f"{text}\n\n[SQL_ACTION_ID_START]{action_id}[SQL_ACTION_ID_END]"

    async def chat(self, user_key: str, message: str, session_id: str | None, project_id: str | None = None) -> tuple[str, str | None, list[dict]]:
        logger.info(f"UseCase: Processing chat message, user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (message or "").strip()
        if not query:
            logger.error("UseCase: Message is required but was empty")
            raise HTTPException(status_code=400, detail="Message is required")

        try:
            logger.info(f"UseCase: Getting agent for user_key={user_key}")
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions:
            logger.error("UseCase: Agent initialized but no MCP servers connected")
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )

        # Đảm bảo có SessionManager
        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")

        # Validate project_id as UUID (from projects.id) if provided
        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                    logger.info(f"UseCase: Using project_id={project_id_uuid}")
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID: {project_id!r}, ignoring")

        # Auto-connect database based on context:
        # - In project: connect to project's SQLite .db file
        # - Outside project: leave as-is (user manages PostgreSQL connection manually via chat)
        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, user_key)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    # Only auto-connect if it's a SQLite path (not placeholder)
                    if db_url and not db_url.startswith("placeholder://"):
                        logger.info(f"UseCase: Auto-connecting to project database: {db_url}")
                        connect_result = await agent.connect_to_project_db(db_url)
                        logger.info(f"UseCase: Database connection result: {connect_result}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database: {e}")

        # Nếu có session_id → cố gắng load session đó
        loaded = False
        current_session_id: str | None = session_id
        if session_id:
            logger.info(f"UseCase: Attempting to load session: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session: {session_id}")

        # Nếu không có session_id hoặc load thất bại:
        # - Nếu đang trong project (project_id_uuid) → tạo session mới gắn với project đó
        # - Nếu không có project → tạo session mới global cho user
        if not loaded:
            logger.info(f"UseCase: Creating new session, project_id={project_id_uuid}")
            current_session_id = await agent.session_manager.create_session(session_name=None, project_id=project_id_uuid)

        # Important: pass the *same* session_id through to HybridOrchestrator so that
        # the "preview/approval" flow can find the stored SQL state later.
        if not current_session_id:
            # Should never happen, but keep it safe: fallback to the value inside session_manager.
            current_session_id = (await agent.session_manager.get_session_info()).get("session_id") or None

        logger.info(f"UseCase: Processing query: {query[:100]}...")
        try:
            # IMPORTANT: pass real chat session_id into orchestrator so pending approval state
            # (e.g. SQL execute flow) is stored/retrieved under the same key.
            result = await agent.process_query(query, verbose=False, session_id=current_session_id)

            # HybridOrchestrator returns dict with response, agent_id, session_id, approach, intent
            if isinstance(result, dict):
                response_text = result.get("response", "")
                agent_id = result.get("agent_id", "unknown")
                approach = result.get("approach")
                session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
                current_session_id = session_info.get("session_id") if session_info else result.get("session_id")

                sql_preview = self._extract_last_mutation_sql_block(response_text)
                if sql_preview:
                    action_id = str(uuid.uuid4())
                    response_text = self._attach_sql_action_id_marker(response_text, action_id)

                logger.info(f"UseCase: Query processed successfully, session_id={current_session_id}, agent={agent_id}, approach={approach}")

                # Workflow path bypasses BaseAgent chat loop, so persist user + assistant here.
                if approach == "workflow":
                    await agent.session_manager.add_message("user", query)
                    if (response_text or "").strip():
                        await agent.session_manager.add_message("assistant", response_text)
            else:
                # Legacy format (tuple)
                response_text, agent_id = result
                session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
                current_session_id = session_info.get("session_id") if session_info else None

            # Legacy tuple path may also contain SQL preview; attach action_id marker if missing.
            if not re.search(r"\[SQL_ACTION_ID_START\].*?\[SQL_ACTION_ID_END\]", response_text or "", flags=re.DOTALL):
                sql_preview = self._extract_last_mutation_sql_block(response_text)
                if sql_preview:
                    action_id = str(uuid.uuid4())
                    response_text = self._attach_sql_action_id_marker(response_text, action_id)

            tool_events: list[dict] = []
            if isinstance(result, dict):
                tool_events = result.get("tool_events") or []
                if not isinstance(tool_events, list):
                    tool_events = []

            return response_text, current_session_id, tool_events
        except Exception as e:
            logger.error(f"UseCase: Error processing query: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}") from e

    async def execute_sql(
        self,
        user_key: str,
        sql: str,
        action_id: str | None,
        session_id: str | None,
        project_id: str | None = None,
        lang: str = "en",
        lock_only: bool = False,
        lock_state: str | None = None,
    ) -> tuple[str, str | None, list[dict]]:
        """
        Execute a raw SQL statement that was previously previewed to the user.
        This reuses the same agent + project DB auto-connect + session logic as chat().
        """
        logger.info(f"UseCase: Executing SQL for user_key={user_key}, session_id={session_id}, project_id={project_id}")
        query = (sql or "").strip()
        if not query:
            logger.error("UseCase: SQL is required but was empty")
            raise HTTPException(status_code=400, detail="SQL is required")

        try:
            logger.info(f"UseCase: Getting agent for user_key={user_key} (execute_sql)")
            agent = await self._agent_repo.get_agent(user_key=user_key)
        except Exception as e:
            logger.error(f"UseCase: Error initializing agent (execute_sql): {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

        if not agent.sessions:
            logger.error("UseCase: Agent initialized but no MCP servers connected (execute_sql)")
            raise HTTPException(
                status_code=500,
                detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
            )

        if not agent.session_manager:
            logger.error("UseCase: Session manager is not available for this agent (execute_sql)")
            raise HTTPException(status_code=500, detail="Session manager is not available for this agent")

        # Validate project_id as UUID (from projects.id) if provided
        project_id_uuid: str | None = None
        if project_id:
            s = str(project_id).strip()
            if s:
                try:
                    uuid.UUID(s)
                    project_id_uuid = s
                    logger.info(f"UseCase: Using project_id={project_id_uuid} (execute_sql)")
                except (ValueError, TypeError):
                    logger.warning(f"UseCase: Invalid project_id UUID in execute_sql: {project_id!r}, ignoring")

        # Auto-connect database based on context (same as chat)
        if project_id_uuid and self._project_repo:
            try:
                project = await self._project_repo.get_project_by_id(project_id_uuid, user_key)
                if project and project.get("db_url"):
                    db_url = project["db_url"]
                    if db_url and not db_url.startswith("placeholder://"):
                        logger.info(f"UseCase: Auto-connecting to project database (execute_sql): {db_url}")
                        connect_result = await agent.connect_to_project_db(db_url)
                        logger.info(f"UseCase: Database connection result (execute_sql): {connect_result}")
            except Exception as e:
                logger.warning(f"UseCase: Failed to auto-connect project database in execute_sql: {e}")

        # Load or create session (so history / project context is consistent)
        loaded = False
        if session_id:
            logger.info(f"UseCase: Attempting to load session in execute_sql: {session_id}")
            loaded = await agent.session_manager.load_session(session_id)
            if loaded:
                logger.info(f"UseCase: Successfully loaded session in execute_sql: {session_id}")
            else:
                logger.warning(f"UseCase: Failed to load session in execute_sql: {session_id}")

        if not loaded:
            logger.info(f"UseCase: Creating new session for execute_sql, project_id={project_id_uuid}")
            await agent.session_manager.create_session(session_name=None, project_id=project_id_uuid)

        session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
        current_session_id = session_info.get("session_id") if session_info else None

        # lock_only path: persist one-time lock in DB without executing SQL.
        if lock_only and current_session_id:
            if not (action_id or "").strip():
                raise HTTPException(status_code=400, detail="action_id is required for SQL action locking")
            state_to_store = (lock_state or "executed").strip().lower()
            if state_to_store not in {"executed", "cancelled"}:
                state_to_store = "executed"
            await agent.session_manager.set_sql_action_state(current_session_id, action_id, state_to_store)
            logger.info(f"UseCase: SQL action locked (lock_only={state_to_store}), session_id={current_session_id}, action_id={action_id}")
            return "SQL action locked", current_session_id, []

        # Guardrail: CREATE TABLE can only be executed if session has
        # pending approval payload kind=create_table_after_schema_confirm
        # and SQL exactly matches the approved pending SQL.
        is_create_table = bool(re.match(r"^\s*CREATE\s+TABLE\b", query, flags=re.IGNORECASE))
        if is_create_table:
            session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
            current_session_id = session_info.get("session_id") if session_info else None
            pending = await agent.session_manager.get_pending_approval(current_session_id) if current_session_id else None
            if not pending:
                raise HTTPException(
                    status_code=400,
                    detail="CREATE TABLE is blocked: no pending schema approval found. Please confirm schema first.",
                )

            pending_kind = str(pending.get("kind") or "")
            pending_sql = str(pending.get("sql") or "").strip()
            normalized_query = query.rstrip(";").strip()
            normalized_pending_sql = pending_sql.rstrip(";").strip()

            if pending_kind != "create_table_after_schema_confirm":
                raise HTTPException(
                    status_code=400,
                    detail="CREATE TABLE is blocked: pending approval kind is invalid for table creation.",
                )

            if normalized_query != normalized_pending_sql:
                raise HTTPException(
                    status_code=400,
                    detail="CREATE TABLE is blocked: SQL does not match the approved schema preview.",
                )

        logger.info(f"UseCase: Executing SQL (first 200 chars): {query[:200]}...")
        try:
            # HybridOrchestrator may have approve_and_execute method
            if hasattr(agent, 'approve_and_execute'):
                session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
                current_session_id = session_info.get("session_id") if session_info else None
                result = await agent.approve_and_execute(session_id=current_session_id, approved=True)

                # Approval preview state is stored in-memory (RAM) inside HybridOrchestrator.
                # If the server reloaded or state is missing, fallback to executing the SQL
                # that the frontend already extracted from the preview message.
                approve_result_text = str(result.get("response", "")) if isinstance(result, dict) else str(result)
                if approve_result_text.strip().startswith("Session ") and " not found" in approve_result_text:
                    logger.warning(
                        "UseCase: approval state missing, falling back to direct execute_sql. session_id=%s",
                        current_session_id,
                    )
                    result = await agent.execute_sql(query, lang=lang)
            else:
                # Legacy: call execute_sql directly
                result = await agent.execute_sql(query, lang=lang)
                session_info = await agent.session_manager.get_session_info() if agent.session_manager else None
                current_session_id = session_info.get("session_id") if session_info else None

            if isinstance(result, dict):
                result_text = str(result.get("response", ""))
                tool_events = result.get("tool_events") or []
                if not isinstance(tool_events, list):
                    tool_events = []
            else:
                result_text = str(result)
                tool_events = []

            if current_session_id and (action_id or "").strip():
                await agent.session_manager.set_sql_action_state(current_session_id, action_id, "executed")

            # Persist assistant execution result so it survives page reload/history fetch.
            if agent.session_manager and (result_text or "").strip():
                await agent.session_manager.add_message("assistant", result_text)

            logger.info(f"UseCase: SQL executed successfully, session_id={current_session_id}")
            return result_text, current_session_id, tool_events
        except Exception as e:
            logger.error(f"UseCase: Error executing SQL: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to execute SQL: {str(e)}") from e

