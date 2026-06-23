"""ChatService — wires the per-request ContextVar with auth + project + history.

db_url does NOT come from the client: resolved server-side from the project (after ownership/share check)
→ matches the design principle (client/LLM never sees the DSN).

Supports:
- Session owner: full permission (edit).
- Share recipient: gated by permission vs the route access_level.
- Files uploaded in the session: attach a session adapter (DbContext.session).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent import titling
from app.agent.context import DbContext, RequestContext, reset_ctx, set_ctx
from app.agent.orchestration import get_orchestrator
from app.agent.orchestration.orchestrator import ChatResult
from app.agent.adapters import make_adapter
from app.agent.pool import get_connection_pool, user_pool_key
from app.features.auth import repository as auth_repo
from app.features.files import service as files_service
from app.features.projects import service as proj_service
from app.features.sessions import repository as sess_repo

logger = logging.getLogger("chat")


class ChatError(Exception):
    pass


# Async callback used to stream progress stages to the client (SSE). Default is a no-op so
# non-streaming callers (e.g. tests) can ignore it. Stages themselves originate from the
# graph nodes (see app.agent.graph.stages); this layer only forwards the callback.
StageCb = Callable[[str], Awaitable[None]]


async def _noop_stage(_message: str) -> None:
    return None


@dataclass
class _Access:
    project_id: str
    db_url: str | None  # None when no primary DB is configured (file-only chat is still allowed)


async def _authorize(user_id: str, session_id: str) -> _Access:
    """Determine project + db_url for an owned session.

    db_url may be None: a session with no primary DB is still allowed (the user can query
    uploaded files only). The "nothing to query" case is enforced in _build_ctx, which knows
    whether the turn actually resolves to a usable primary or session adapter.
    """
    logger.info("→ _authorize(user_id=%r session_id=%r)", user_id, session_id)
    row = await sess_repo.get_session(session_id, user_id)
    if row is None:
        raise ChatError("Session does not exist or you do not have access.")
    project_id = row["project_id"]

    # Project-bound session: DB from the project (may be None if not configured yet).
    if project_id:
        db_url = await proj_service.resolve_db_url(project_id, user_id)
        return _Access(project_id=project_id, db_url=db_url)

    # Global session (no project): DB from the user's active connection (may be None).
    db_url = await auth_repo.get_active_db_url(user_id)
    db_url = db_url if (db_url and proj_service.is_configured(db_url)) else None
    # Pool key per user so global sessions of different users don't collide.
    return _Access(project_id=user_pool_key(user_id), db_url=db_url)


# Sentinel the frontend sends in active_file_ids to mean "the project / primary DB".
PRIMARY_DB_SENTINEL = "__primary_db__"


async def _build_ctx(
    user_id: str, session_id: str, access: _Access, active_file_ids: list[str] | None = None
) -> RequestContext:
    """Build the per-request DB scope from the data sources picked for this turn.

    active_file_ids:
    - contains PRIMARY_DB_SENTINEL → the primary (project/external) DB is in scope.
    - file ids → only those uploaded files' tables are in scope.
    - None (e.g. approval/resume, which targets the primary DB) → primary DB only.
    """
    logger.info(
        "→ _build_ctx(user_id=%r session_id=%r active_file_ids=%r)",
        user_id, session_id, active_file_ids,
    )  # autolog (access.db_url is intentionally not logged — it holds the DSN)

    # No selection (resume) is treated as "the database": primary in scope, no files.
    ids = active_file_ids if active_file_ids is not None else [PRIMARY_DB_SENTINEL]
    want_primary = PRIMARY_DB_SENTINEL in ids
    file_ids = [fid for fid in ids if fid != PRIMARY_DB_SENTINEL]

    # Primary DB only when it's both wanted and actually configured (db_url may be None for
    # a file-only session that has no database connected).
    pool = get_connection_pool()
    primary = (
        await pool.adapter_for(access.project_id, access.db_url)
        if (want_primary and access.db_url) else None
    )

    # session-file adapter (only when files are in scope). Not pooled: request-scoped,
    # disposed by the caller (see _dispose_ctx) at the end of the request.
    session_adapter = None
    allowed: frozenset[str] | None = None
    if file_ids:
        sqlite_path, tables = await files_service.session_db(session_id, file_ids)
        if sqlite_path:
            session_adapter = make_adapter(sqlite_path, allowed_tables=tables)
            allowed = tables

    active = primary or session_adapter
    if active is None:
        # Neither a database nor an in-scope file resolved → nothing to query.
        raise ChatError("No data source available. Connect a database or upload a file to query.")
    return RequestContext(
        user_id=user_id,
        session_id=session_id,
        project_id=access.project_id,
        db=DbContext(
            primary=primary,
            session=session_adapter,
            allowed_tables=allowed,
            engine=active.engine_name,
        ),
    )


async def _dispose_ctx(ctx: RequestContext) -> None:
    """Release request-scoped resources. The session-file adapter is not pooled, so
    its engine must be disposed once the request is done (the primary adapter is pooled)."""
    if ctx.db.session is not None:
        await ctx.db.session.dispose()


async def handle(
    user_id: str,
    session_id: str,
    message: str,
    active_file_ids: list[str] | None = None,
    on_stage: StageCb | None = None,
) -> ChatResult:
    logger.info("→ handle(user_id=%r session_id=%r message=%r)", user_id, session_id, message)
    emit = on_stage or _noop_stage
    access = await _authorize(user_id, session_id)
    history = await sess_repo.get_history(session_id)
    is_first_message = not history
    orch = get_orchestrator()

    # Normalize the turn once (resolve references + English) → one standalone query used
    # by BOTH the classifier and every downstream route. Uses raw recent history; the
    # (expensive) running summary is computed lazily inside process_query, only for the
    # tool-loop routes that actually need conversation memory.
    normalized = await orch.normalize(message, history)

    intent = await orch.classify(normalized)
    # if off-topic, return result that Chat system does not support
    if intent.route == "off_topic":
        return ChatResult(response="Sorry, I can only help with database-related questions. Please ask a database-related question.", route=intent.route)

    # Ambiguous request → ask back, without the cost of building ctx / running the agent.
    if intent.needs_clarification:
        result = ChatResult(
            response=intent.clarification_question or "Could you clarify your request?",
            needs_clarification=True,
        )
    else:
        ctx = await _build_ctx(user_id, session_id, access, active_file_ids)
        token = set_ctx(ctx)
        try:
            result = await orch.process_query(
                normalized, intent=intent, history=history, on_stage=emit
            )
        finally:
            reset_ctx(token)
            await _dispose_ctx(ctx)

    await sess_repo.add_message(session_id, "user", message)
    await sess_repo.add_message(session_id, "assistant", result.response, result.tool_events)
    if result.action_id and result.action_state:
        await sess_repo.set_sql_action(session_id, result.action_id, result.action_state)

    # Auto-name the session from its first user message (best-effort, never fatal).
    if is_first_message:
        try:
            await sess_repo.set_title(session_id, user_id, await titling.title_from_first_message(message))
        except Exception as e:  # noqa: BLE001
            logger.warning("auto-title failed for session=%s: %s", session_id, e)

    return result


async def approve(
    user_id: str, session_id: str, approved: bool, edited_schema: dict | None = None
) -> ChatResult:
    logger.info("→ approve(user_id=%r session_id=%r approved=%r)", user_id, session_id, approved)  # autolog
    access = await _authorize(user_id, session_id)
    ctx = await _build_ctx(user_id, session_id, access)
    token = set_ctx(ctx)
    try:
        # SQL is NOT sent by the client; for create_table the client may send the edited schema
        # (structured columns) and the server rebuilds + re-verifies the SQL from it.
        result = await get_orchestrator().resume(session_id, approved, edited_schema=edited_schema)
    finally:
        reset_ctx(token)
        await _dispose_ctx(ctx)
    await sess_repo.add_message(session_id, "assistant", result.response, result.tool_events)
    if result.action_id and result.action_state:
        await sess_repo.set_sql_action(session_id, result.action_id, result.action_state)
    return result
