"""Direct SQL execute + data export (used by the FE 'Execute' button and export menu).

Resolves the DB the same way chat does: session→project / session→user / project / user.
db_url stays server-side; only results are returned.
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.context import DbContext, RequestContext, reset_ctx, set_ctx
from app.agent.pool import get_connection_pool, user_pool_key
from app.features.auth import repository as auth_repo
from app.features.auth.deps import get_current_user_id
from app.features.projects import service as proj_service
from app.features.sessions import repository as sess_repo


router = APIRouter(tags=["query"])


async def _resolve(user_id: str, session_id: str | None, project_id: str | None) -> tuple[str, str]:
    """Return (pool_key, db_url). Raise 400 if no DB is connected."""
    pid = project_id
    if session_id:
        s = await sess_repo.get_session(session_id, user_id)
        if s:
            pid = s["project_id"] or pid
    if pid:
        db_url = await proj_service.resolve_db_url(pid, user_id)
        if db_url:
            return pid, db_url
    db_url = await auth_repo.get_active_db_url(user_id)
    if db_url:
        return user_pool_key(user_id), db_url
    raise HTTPException(status_code=400, detail="No database connected")


async def _adapter(user_id: str, session_id: str | None, project_id: str | None):
    key, db_url = await _resolve(user_id, session_id, project_id)
    return await get_connection_pool().adapter_for(key, db_url)


def _md(res) -> str:        
    if not res.columns:
        return f"_OK ({res.rowcount} rows affected)._"
    head = "| " + " | ".join(res.columns) + " |"
    sep = "| " + " | ".join("---" for _ in res.columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in res.rows[:100]]
    return "\n".join([head, sep, *body])


@router.post("/api/sql/execute")
async def execute_sql(body: dict, user_id: str = Depends(get_current_user_id)):
    session_id = body.get("session_id")
    action_id = body.get("action_id")
    # lock_only: the UI just records the approve/cancel decision; nothing to run.
    if body.get("lock_only"):
        if session_id and action_id and body.get("lock_state"):
            await sess_repo.set_sql_action(session_id, action_id, str(body["lock_state"]))
        return {"success": True, "response": "", "session_id": session_id, "tool_events": [],
                "pending_workflow_resume": False}
    sql = (body.get("sql") or "").strip()
    if not sql:
        return {"success": False, "error": "Empty SQL"}
    adapter = await _adapter(user_id, session_id, body.get("project_id"))
    ctx = RequestContext(user_id=user_id, session_id=session_id,
                         db=DbContext(primary=adapter, engine=adapter.engine_name))
    token = set_ctx(ctx)
    try:
        res = await adapter.execute(sql)
    except Exception as e:  # noqa: BLE001
        reset_ctx(token)
        if session_id and action_id:
            await sess_repo.set_sql_action(session_id, action_id, "failed")
        return {"success": False, "error": str(e)}
    reset_ctx(token)
    if session_id and action_id:
        await sess_repo.set_sql_action(session_id, action_id, "executed")
    return {
        "success": True, "response": _md(res), "session_id": session_id,
        "pending_workflow_resume": False,
        "tool_events": [{"tool": "execute_query", "type": "sql_execution",
                         "payload": {"sql": sql, "result": _md(res)}}],
    }


@router.post("/api/export")
async def export_data(table_name: str, columns: str = "*", where_clause: str | None = None,
                      format: str = "csv", session_id: str | None = None,
                      project_id: str | None = None, user_id: str = Depends(get_current_user_id)):
    import re

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
        raise HTTPException(status_code=400, detail="Invalid table name")
    adapter = await _adapter(user_id, session_id, project_id)
    sql = f'SELECT {columns} FROM "{table_name}"'
    if where_clause:
        sql += f" WHERE {where_clause}"
    ctx = RequestContext(user_id=user_id, session_id=session_id,
                         db=DbContext(primary=adapter, engine=adapter.engine_name))
    token = set_ctx(ctx)
    try:
        res = await adapter.execute(sql)
    finally:
        reset_ctx(token)

    import pandas as pd

    df = pd.DataFrame([dict(zip(res.columns, row)) for row in res.rows], columns=res.columns or None)
    if format == "excel":
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{table_name}.xlsx"'},
        )
    csv = df.to_csv(index=False)
    return StreamingResponse(
        iter([csv]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table_name}.csv"'},
    )
