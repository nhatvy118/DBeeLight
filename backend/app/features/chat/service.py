"""ChatService — wires the per-request ContextVar with auth + project + history.

db_url does NOT come from the client: resolved server-side from the project (after ownership/share check)
→ matches the design principle (client/LLM never sees the DSN).

Supports:
- Session owner: full permission (edit).
- Share recipient: gated by permission vs the route access_level.
- Uploaded Excel workbooks: edited via the Excel tools (not queried as a DB).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent import titling
from app.agent.context import DbContext, RequestContext, reset_ctx, set_ctx
from app.agent.orchestration import get_orchestrator
from app.agent.orchestration.intent import Intent
from app.agent.orchestration.orchestrator import ChatResult
from app.agent.pool import get_connection_pool
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
    if not project_id:
        # Legacy global session (pre-unification) — no project, nothing to query.
        raise ChatError("No data source available. Open or create a project to query.")

    # Every data source is a project (internal SQLite or external DB). Access = owner OR shared-with
    # (a viewer can query a project shared with them); write is gated separately by role.
    db_url = await proj_service.resolve_db_url_for_access(project_id, user_id)
    return _Access(project_id=project_id, db_url=db_url)



async def _build_ctx(
    user_id: str, session_id: str, access: _Access, active_file_ids: list[str] | None = None,
    *, require_source: bool = True,
) -> RequestContext:
    """Build the per-request DB scope. The only queryable source is the project's primary DB
    (project SQLite or external Postgres). Uploaded files are Excel workbooks edited via the
    Excel tools, not queried — so they never form a SQL scope here.

    `require_source=False` (the Excel route) allows a turn with no queryable DB at all.
    `active_file_ids` is accepted for signature symmetry but no longer scopes the query.
    """
    logger.info(
        "→ _build_ctx(user_id=%r session_id=%r active_file_ids=%r)",
        user_id, session_id, active_file_ids,
    )  # autolog (access.db_url is intentionally not logged — it holds the DSN)

    pool = get_connection_pool()
    primary = await pool.adapter_for(access.project_id, access.db_url) if access.db_url else None

    if primary is None and require_source:
        raise ChatError("No data source available. Connect a database to query.")
    return RequestContext(
        user_id=user_id,
        session_id=session_id,
        project_id=access.project_id,
        db=DbContext(
            primary=primary,
            # engine is unused when there's no primary (Excel route) → harmless default.
            engine=primary.engine_name if primary is not None else "sqlite",
        ),
    )


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

    # Supersede: a NEW message cancels any gated action still waiting for confirmation, so a stale
    # "Confirm & create table" / SQL-preview card can't conflict with or corrupt this turn.
    # (Confirming goes through approve(), not here, so this only fires when the user moved on.)
    cancelled_action_ids: list[str] = []
    for cancelled_id in await orch.cancel_pending(session_id):
        await sess_repo.set_sql_action(session_id, cancelled_id, "cancelled")
        cancelled_action_ids.append(cancelled_id)

    # Normalize the turn once (resolve references + English) → one standalone query used
    # by BOTH the classifier and every downstream route. Uses raw recent history; the
    # (expensive) running summary is computed lazily inside process_query, only for the
    # tool-loop routes that actually need conversation memory.
    normalized = await orch.normalize(message, history)

    # Routing is SELECTION-driven for Excel: if the user has an uploaded workbook selected as an
    # active data source this turn, force the Excel route (read/edit that file) and SKIP the
    # classifier — no LLM call. With no workbook selected, classify normally into a DB route, so the
    # same session can both edit a workbook (when picked) and query the project DB (when not).
    excel_paths = await files_service.excel_file_paths(session_id, active_file_ids or [])
    if excel_paths:
        intent = Intent(route="excel")
    else:
        intent = await orch.classify(normalized)

    # Off-topic: don't run the agent. Reply with a warm, language-matched decline (built from the
    # RAW message so it matches the user's language — `normalized` is English), and persist the turn
    # like any other so it shows up in history.
    if intent.route == "off_topic":
        decline = await orch.offtopic_reply(message)
        await sess_repo.add_message(session_id, "user", message)
        await sess_repo.add_message(session_id, "assistant", decline)
        return ChatResult(response=decline, route=intent.route, cancelled_action_ids=cancelled_action_ids)

    # Write gate: only owners and technical users with EDIT access may change data/schema. Viewers
    # are always read-only; a technical user with a VIEW-only share is read-only too. Refuse up
    # front (the friendly "RefusalCard"). Read routes (lookup/analysis/chart) fall through normally.
    if intent.route in ("db_mutation", "db_create_table"):
        me = await auth_repo.get_user(user_id)
        role = (me or {}).get("role")
        can_edit = await proj_service.user_can_edit(access.project_id, user_id, role)
        if not can_edit:
            await sess_repo.add_message(session_id, "user", message)
            refusal = (
                "I can't change data here — you have view-only access to this project. I can answer "
                "questions and build charts, but I can't add, edit or delete anything."
            )
            await sess_repo.add_message(session_id, "assistant", refusal)
            return ChatResult(response=refusal, route=intent.route, cancelled_action_ids=cancelled_action_ids)

    # Ambiguous request → ask back, without the cost of building ctx / running the agent.
    if intent.needs_clarification:
        result = ChatResult(
            response=intent.clarification_question or "Could you clarify your request?",
            needs_clarification=True,
        )
    else:
        # The Excel route edits workbooks via the excel-server, not the DB — so it must NOT require
        # a queryable data source (a workbook-only session has none).
        is_excel = intent.route == "excel"
        ctx = await _build_ctx(user_id, session_id, access, active_file_ids, require_source=not is_excel)
        token = set_ctx(ctx)
        # Excel turns: the workbook(s) to open were already resolved above (excel_paths = the picked
        # files). Snapshot the folder so we can detect what the agent created/modified and offer an
        # in-chat download afterwards.
        excel_before = files_service.snapshot_excel_dir(session_id) if is_excel else {}
        try:
            result = await orch.process_query(
                normalized, intent=intent, history=history, on_stage=emit,
                excel_file_paths=excel_paths if is_excel else None,
            )
            if is_excel:
                # Stateless excel: exports come back inline (base64) and the server deletes
                # the session's workbooks + `files` rows — the FE keeps the only copy.
                exports = await files_service.collect_excel_outputs_inline(user_id, session_id, excel_before)
                if exports:
                    result.tool_events = (result.tool_events or []) + exports
        finally:
            reset_ctx(token)

    result.cancelled_action_ids = cancelled_action_ids  # superseded cards → FE disables them live
    await sess_repo.add_message(session_id, "user", message)
    # base64 payloads are for the LIVE response only — never persisted (they would bloat the
    # messages table and every GET /messages). The persisted card keeps metadata only; on
    # reload the FE re-attaches the blob from the device's IndexedDB.
    persisted_events = [
        {**ev, "payload": {k: v for k, v in ev["payload"].items() if k != "base64"}}
        if ev.get("type") == "file_export" and (ev.get("payload") or {}).get("ephemeral")
        else ev
        for ev in (result.tool_events or [])
    ] or None
    await sess_repo.add_message(session_id, "assistant", result.response, persisted_events)
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
    await sess_repo.add_message(session_id, "assistant", result.response, result.tool_events)
    if result.action_id and result.action_state:
        await sess_repo.set_sql_action(session_id, result.action_id, result.action_state)
    return result
