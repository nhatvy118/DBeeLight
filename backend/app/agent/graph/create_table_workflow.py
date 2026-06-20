"""CreateTable workflow (LangGraph) — 2 phases: review columns → create table.

Phase 1 (SCHEMA_PREVIEW): generate a column spec + CREATE TABLE SQL, show the column table for
the user to review data types (interrupt). Phase 2 (EXECUTION): run CREATE after approval.
"""
from __future__ import annotations

import json
import logging
import re
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from app.agent.graph import dbtools
from app.agent.graph.checkpointer import get_async_checkpointer
from app.agent.graph.sql_verification import tier1_static
from app.features.metadata import repository as metadata_repo
from app.features.metadata.scope import resolve_scope
from app.agent.graph.state import (
    OUTPUT_EXECUTION,
    OUTPUT_SCHEMA_PREVIEW,
    AgentState,
    StageType,
    create_initial_state,
)
from app.agent.llm import get_llm
from app.config import get_settings

logger = logging.getLogger("agent.graph.create_table")


# --- Rebuild CREATE TABLE from the user-edited (structured) schema ---------------
# The columns come from the client editor, so identifiers/types are sanitized and the
# rebuilt SQL is re-verified by tier1_static (must be DDL) before it can run.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?$")
_DEFAULT_KEYWORDS = {"NULL", "TRUE", "FALSE", "CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"}
_INT_TYPES = {"INTEGER", "INT", "SMALLINT", "BIGINT", "SERIAL", "BIGSERIAL"}

# Reserved SQL keywords that can't be used as an unquoted table/column name — an
# identifier matching one (e.g. SELECT, ORDER, USER) is rejected before building SQL so
# the user gets a clear message instead of a cryptic driver syntax error. Union of the
# common reserved words across SQLite and PostgreSQL (kept uppercase for case-insensitive
# comparison). This is intentionally broad: better to ask the user to rename than to emit
# SQL that breaks on one engine.
_RESERVED_KEYWORDS = frozenset({
    "ADD", "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "AUTHORIZATION", "BEGIN",
    "BETWEEN", "BINARY", "BOTH", "BY", "CASE", "CAST", "CHECK", "COLLATE", "COLUMN",
    "COMMIT", "CONSTRAINT", "CREATE", "CROSS", "CURRENT", "CURRENT_DATE", "CURRENT_TIME",
    "CURRENT_TIMESTAMP", "CURRENT_USER", "DATABASE", "DEFAULT", "DEFERRABLE", "DELETE",
    "DESC", "DISTINCT", "DO", "DROP", "ELSE", "END", "EXCEPT", "EXISTS", "FALSE", "FETCH",
    "FOR", "FOREIGN", "FROM", "FULL", "GRANT", "GROUP", "HAVING", "IN", "INDEX", "INNER",
    "INSERT", "INTERSECT", "INTO", "IS", "JOIN", "LEADING", "LEFT", "LIKE", "LIMIT",
    "LOCALTIME", "LOCALTIMESTAMP", "NATURAL", "NOT", "NULL", "OFFSET", "ON", "ONLY", "OR",
    "ORDER", "OUTER", "OVER", "PRIMARY", "REFERENCES", "RETURNING", "RIGHT", "ROLLBACK",
    "SELECT", "SESSION_USER", "SET", "SOME", "TABLE", "THEN", "TO", "TRAILING",
    "TRANSACTION", "TRIGGER", "TRUE", "UNION", "UNIQUE", "UPDATE", "USER", "USING",
    "VALUES", "VIEW", "WHEN", "WHERE", "WINDOW", "WITH",
})

# Logical type → concrete type per engine. The LLM/editor emits a logical type (engine-
# agnostic); the builder maps it so the same column produces valid SQL on either engine.
# Unknown types fall through unchanged (already sanitized by _safe_type).
_TYPE_MAP: dict[str, dict[str, str]] = {
    "INT":       {"sqlite": "INTEGER", "postgresql": "INTEGER"},
    "INTEGER":   {"sqlite": "INTEGER", "postgresql": "INTEGER"},
    "SMALLINT":  {"sqlite": "INTEGER", "postgresql": "SMALLINT"},
    "BIGINT":    {"sqlite": "INTEGER", "postgresql": "BIGINT"},
    "TEXT":      {"sqlite": "TEXT", "postgresql": "TEXT"},
    "STRING":    {"sqlite": "TEXT", "postgresql": "TEXT"},
    "VARCHAR":   {"sqlite": "TEXT", "postgresql": "VARCHAR"},   # keeps (n) on postgres
    "CHAR":      {"sqlite": "TEXT", "postgresql": "CHAR"},
    "BOOLEAN":   {"sqlite": "BOOLEAN", "postgresql": "BOOLEAN"},  # sqlite: NUMERIC affinity, 0/1
    "BOOL":      {"sqlite": "BOOLEAN", "postgresql": "BOOLEAN"},
    "REAL":      {"sqlite": "REAL", "postgresql": "REAL"},
    "FLOAT":     {"sqlite": "REAL", "postgresql": "REAL"},
    "DOUBLE":    {"sqlite": "REAL", "postgresql": "DOUBLE PRECISION"},
    "DECIMAL":   {"sqlite": "NUMERIC", "postgresql": "NUMERIC"},  # keeps (p,s)
    "NUMERIC":   {"sqlite": "NUMERIC", "postgresql": "NUMERIC"},
    "DATE":      {"sqlite": "DATE", "postgresql": "DATE"},
    "TIME":      {"sqlite": "TEXT", "postgresql": "TIME"},
    "DATETIME":  {"sqlite": "DATETIME", "postgresql": "TIMESTAMP"},  # normalize datetime→timestamp
    "TIMESTAMP": {"sqlite": "DATETIME", "postgresql": "TIMESTAMP"},
    "JSON":      {"sqlite": "TEXT", "postgresql": "JSONB"},
    "UUID":      {"sqlite": "TEXT", "postgresql": "UUID"},
    "BLOB":      {"sqlite": "BLOB", "postgresql": "BYTEA"},
    "BYTEA":     {"sqlite": "BLOB", "postgresql": "BYTEA"},
}
# Mapped types that keep their (n) / (p,s) parameters.
_PARAM_TYPES = {"VARCHAR", "CHAR", "NUMERIC", "DECIMAL"}

# Single source of truth for the logical column types offered to BOTH the LLM (prompt)
# and the FE editor dropdown (sent in the schema_preview event). Each maps to a concrete
# per-engine type via _TYPE_MAP at build time, so the UI never has to know the engine.
LOGICAL_TYPES = [
    "integer", "bigint", "smallint", "text", "varchar(255)", "boolean",
    "real", "double", "decimal(10,2)", "date", "time", "timestamp",
    "json", "uuid", "blob",
]


def _is_int_type(t: str) -> bool:
    return t.upper().split("(")[0].strip() in _INT_TYPES


def _map_type(raw: object, engine: str) -> str:
    """Sanitize a column type and map it to the concrete type for `engine`.
    Unknown types pass through (sanitized)."""
    tt = _safe_type(raw)  # validates + uppercases, may include "(...)"
    m = re.match(r"^([A-Z ]+?)\s*(\(\s*\d+\s*(?:,\s*\d+\s*)?\))?$", tt)
    base = m.group(1).strip() if m else tt
    params = (m.group(2) if m else None) or ""
    mapped = _TYPE_MAP.get(base, {}).get(engine)
    if mapped is None:
        return tt  # unknown type → keep as the user/LLM wrote it (already safe)
    return f"{mapped}{params}" if params and mapped in _PARAM_TYPES else mapped


def _safe_ident(name: object) -> str:
    n = str(name or "").strip()
    if not _IDENT_RE.match(n):
        raise ValueError(f"invalid name {name!r}")
    return f'"{n}"'


def _safe_type(t: object) -> str:
    tt = str(t or "").strip()
    if not _TYPE_RE.match(tt):
        raise ValueError(f"invalid type {t!r}")
    return tt.upper()


def _safe_default(v: object) -> str:
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s  # numeric literal
    if s.upper() in _DEFAULT_KEYWORDS:
        return s.upper()
    return "'" + s.replace("'", "''") + "'"  # quoted string literal (escaped)


def _build_create_sql(table: object, columns: list[dict], engine: str = "sqlite") -> str:
    """Build a CREATE TABLE from the editor's structured columns. Raises ValueError on
    any unsafe identifier/type (defense-in-depth before tier1_static re-verifies).

    Auto-increment surrogate keys differ by dialect: an INTEGER PRIMARY KEY auto-increments
    on sqlite (via rowid) but NOT on postgresql, which needs SERIAL. So an integer primary
    key is emitted per-engine."""
    tbl = _safe_ident(table)
    defs: list[str] = []
    for c in columns:
        name = _safe_ident(c.get("variable"))
        raw_type = _safe_type(c.get("type"))  # sanitized + uppercased (for int-PK detection)
        is_pk = bool(c.get("primaryKey"))

        # Integer primary key = auto-increment surrogate; let each dialect handle it.
        # SERIAL/BIGSERIAL (postgres) already imply the sequence/default, so skip other flags.
        if is_pk and _is_int_type(raw_type):
            if engine == "postgresql":
                serial = "BIGSERIAL" if raw_type.split("(")[0].strip() in {"BIGINT", "BIGSERIAL"} else "SERIAL"
                defs.append(f"{name} {serial} PRIMARY KEY")
            else:  # sqlite: INTEGER PRIMARY KEY auto-increments via rowid
                defs.append(f"{name} INTEGER PRIMARY KEY")
            continue

        parts = [name, _map_type(c.get("type"), engine)]
        if is_pk:
            parts.append("PRIMARY KEY")
        if c.get("notNull"):
            parts.append("NOT NULL")
        if c.get("unique"):
            parts.append("UNIQUE")
        dv = c.get("defaultValue")
        if dv not in (None, ""):
            parts.append("DEFAULT " + _safe_default(dv))
        defs.append(" ".join(parts))
    if not defs:
        raise ValueError("no columns")
    return f"CREATE TABLE {tbl} (\n  " + ",\n  ".join(defs) + "\n)"


_IDENT_HINT = ("Use only letters, digits and underscores, and start with a letter or "
               "underscore (no spaces or symbols).")


def _validate_schema(table: object, table_description: object, columns: list[dict]) -> str | None:
    """Return a specific, user-friendly reason the schema can't be created, or None if it
    looks valid. Run BEFORE building SQL so the user is told the exact thing to fix — not a
    raw driver error and not a vague 'could not create'. Every table & column also REQUIRES a
    description (the data dictionary)."""
    tname = str(table or "").strip()
    if not tname:
        return "The table needs a name."
    if not _IDENT_RE.match(tname):
        return f"The table name “{tname}” isn’t valid. {_IDENT_HINT}"
    if tname.upper() in _RESERVED_KEYWORDS:
        return f"“{tname}” is a reserved SQL keyword and can’t be used as a table name. Pick another name."
    if not str(table_description or "").strip():
        return "Add a short description for the table (what it stores)."
    if not columns:
        return "Add at least one column."

    seen: set[str] = set()
    pk_count = 0
    for i, c in enumerate(columns, start=1):
        name = str(c.get("variable") or "").strip()
        if not name:
            return f"Column #{i} is missing a name."
        if not _IDENT_RE.match(name):
            return f"The column name “{name}” isn’t valid. {_IDENT_HINT}"
        if name.upper() in _RESERVED_KEYWORDS:
            return f"“{name}” is a reserved SQL keyword and can’t be used as a column name. Pick another name."
        if name.lower() in seen:
            return f"Two columns are named “{name}”. Each column needs a unique name."
        seen.add(name.lower())

        ctype = str(c.get("type") or "").strip()
        if not ctype:
            return f"Column “{name}” is missing a type."
        if not _TYPE_RE.match(ctype):
            return f"“{ctype}” isn’t a valid type for column “{name}”. Pick a type from the list."
        if not str(c.get("description") or "").strip():
            return f"Add a description for column “{name}” (what it means)."

        if c.get("primaryKey"):
            pk_count += 1
    if pk_count > 1:
        return "Only one column can be the primary key, but more than one is marked."
    return None


def _clean_db_error(raw: str) -> str:
    """Strip the driver wrapper from a DB error, keeping the human-readable reason. e.g.
    '(sqlite3.OperationalError) near \"x\": syntax error\\n[SQL: ...]' → 'near \"x\": syntax error'."""
    s = (raw or "").strip().splitlines()[0] if raw else ""
    s = re.sub(r"^\([^)]*\)\s*", "", s).strip()
    return s or "unknown database error"


def _friendly_db_error(table: str, e: Exception) -> str:
    """Map a DB execution error to a specific, user-friendly reason (no raw driver text)."""
    msg = str(e).lower()
    if "already exists" in msg:
        return f"A table named “{table}” already exists. Choose a different name."
    if "duplicate column" in msg:
        return "There are duplicate column names. Each column needs a unique name."
    if "type" in msg and ("does not exist" in msg or "unknown" in msg or "no such" in msg):
        return "One of the column types isn’t supported by the database. Pick a type from the list."
    if "syntax" in msg:
        return f"The database rejected the schema: {_clean_db_error(str(e))}."
    # Unknown — give the real reason from the DB, just without the driver wrapper.
    return f"The table couldn’t be created: {_clean_db_error(str(e))}."


async def _schema_preview(state: AgentState) -> AgentState:
    client = get_llm()
    resp = await client.chat.completions.create(
        model=get_settings().llm_model,
        messages=[
            {"role": "system", "content": (
                "Design ONE new table from the user's request. Output structure only — never "
                "SQL; the server builds the SQL from your columns. Use only what the user "
                "describes; do not invent tables, columns, or constraints they did not mention.\n"
                "Rules:\n"
                f"- type: one of these logical types only (engine-agnostic): {', '.join(LOGICAL_TYPES)}.\n"
                "- primaryKey: exactly ONE column. If the request implies none, add an integer "
                "\"id\". Never mark more than one.\n"
                "- notNull / unique / defaultValue: set only when the request clearly implies it.\n"
                "- identifiers: table and column names must be valid SQL identifiers — start "
                "with a letter or underscore, then letters/digits/underscore only.\n"
                "- description: write a SHORT plain-language meaning for the table and for "
                "EVERY column (what it holds, units, codes) — this is the data dictionary the "
                "query agent will rely on, so never leave one empty.\n"
                "- enumValues: for a categorical/coded column, the list of allowed values IF "
                'the request makes them clear (e.g. status → ["pending","shipped"]); else null.\n'
                "- If the request is vague, use a minimal, sensible set of columns.\n"
                'Return JSON only: {"table": "...", "tableDescription": "...", "columns": '
                '[{"variable": "...", "type": "...", "primaryKey": false, "notNull": false, '
                '"unique": false, "defaultValue": null, "description": "...", "enumValues": null}]}'
            )},
            {"role": "user", "content": state.get("user_message", "")},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        spec = json.loads(resp.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001
        spec = {}

    # No validation here — the schema is just a draft for the user to review/edit. Name
    # collisions, empty columns, and invalid SQL are all checked at approval, AFTER the
    # user has finalized the schema in the editor (see _approval).
    body = "Review the columns and descriptions below, then create the table."
    return {**state, "current_stage": StageType.SCHEMA_PREVIEW.value,
            "output": {"type": OUTPUT_SCHEMA_PREVIEW, "message": body,
                       "table": str(spec.get("table") or "").strip(),
                       "tableDescription": str(spec.get("tableDescription") or "").strip(),
                       "columns": spec.get("columns") or []}}


def _reopen_editor(state: AgentState, message: str, *, table: object = None,
                   table_description: object = None, columns: object = None) -> AgentState:
    """Loop the workflow back to the APPROVAL interrupt so the schema editor re-opens with
    an error message — instead of ending the workflow. The user fixes the schema and
    re-submits, never having to start over. Keeps their columns (passed in, or the last shown)."""
    out = state.get("output") or {}
    return {**state, "approved": False, "current_stage": StageType.SCHEMA_PREVIEW.value,
            "output": {"type": OUTPUT_SCHEMA_PREVIEW, "message": message,
                       "table": table if table is not None else (out.get("table") or ""),
                       "tableDescription": table_description if table_description is not None else (out.get("tableDescription") or ""),
                       "columns": columns if columns is not None else (out.get("columns") or [])}}


async def _approval(state: AgentState) -> AgentState:
    # Resume value is a bool (legacy) or {"approved": bool, "schema": {...edited columns...}}.
    decision = interrupt({"stage": StageType.SCHEMA_PREVIEW.value, "output": state.get("output")})
    approved = decision if isinstance(decision, bool) else bool((decision or {}).get("approved"))
    if not approved:
        return {**state, "approved": False, "current_stage": StageType.DONE.value,
                "output": {**(state.get("output") or {}), "message": "Table creation cancelled.", "cancelled": True}}

    # The user approved, but did they edit the schema in the editor? If so, re-build + re-verify the SQL
    edited = (decision or {}).get("schema") if isinstance(decision, dict) else None
    if not (edited and edited.get("columns")):
        return _reopen_editor(state, "Please define at least one column.")

    cols = edited["columns"]
    table = str(edited.get("tableName") or "").strip()
    table_desc = str(edited.get("tableDescription") or "").strip()

    # Validate the schema up front so the user gets the EXACT thing to fix (bad/duplicate
    # name, missing type/description, >1 primary key, ...), not a raw SQL error later.
    err = _validate_schema(table, table_desc, cols)
    if err:
        return _reopen_editor(state, err, table=table, table_description=table_desc, columns=cols)

    # Name collision on the FINAL (possibly user-renamed) table name.
    existing = await dbtools.list_tables()
    if table.lower() in {t.lower() for t in existing}:
        return _reopen_editor(state, f"A table named “{table}” already exists. Choose a different name.",
                              table=table, table_description=table_desc, columns=cols)

    engine = state.get("engine", "sqlite")
    try:
        sql = _build_create_sql(table, cols, engine)
    except ValueError as e:  # defense-in-depth; _validate_schema should have caught it
        return _reopen_editor(state, f"That schema isn’t valid: {e}.", table=table,
                              table_description=table_desc, columns=cols)
    t1 = tier1_static(sql, engine)
    if not t1.ok or t1.kind != "DDL":
        return _reopen_editor(state, f"That schema isn’t valid: {_clean_db_error(t1.error or t1.kind)}.",
                              table=table, table_description=table_desc, columns=cols)

    # Stash the final schema (+ descriptions) in output so EXECUTION can persist the data
    # dictionary and an EXECUTION failure can re-open the editor with everything intact.
    return {**state, "approved": True, "sql": sql, "current_stage": StageType.EXECUTION.value,
            "output": {"type": OUTPUT_SCHEMA_PREVIEW, "table": table,
                       "tableDescription": table_desc, "columns": cols}}


async def _save_descriptions(out: dict) -> None:
    """Persist the table/column descriptions to the data dictionary. Best-effort — never
    raises (the table is already created). File/session tables are skipped (scope deferred)."""
    table = str(out.get("table") or "").strip()
    scope = resolve_scope(table) if table else None
    if scope is None:
        return
    rows: list[dict] = []
    td = str(out.get("tableDescription") or "").strip()
    if td:
        rows.append({"table": table, "column": None, "description": td})
    for c in out.get("columns") or []:
        d = str(c.get("description") or "").strip()
        var = c.get("variable")
        if d and var:
            enum = c.get("enumValues")
            enum = enum if isinstance(enum, list) and enum else None
            rows.append({"table": table, "column": var, "description": d, "enum": enum})
    try:
        await metadata_repo.upsert_descriptions(scope[0], scope[1], rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to save descriptions for %r: %s", table, e)


async def _execution(state: AgentState) -> AgentState:
    if not state.get("approved"):
        return {**state, "output": {"type": "execution_skipped", "message": "Cancelled."}}
    sql = state.get("sql") or ""
    table = str((state.get("output") or {}).get("table") or "")
    try:
        await dbtools.run(sql)
    except Exception as e:  # noqa: BLE001
        # DB rejected the CREATE → re-open the editor with a specific reason so the user can fix it.
        logger.warning("create_table execution failed for %r: %s", table, e)  # raw detail for devs
        return _reopen_editor(state, _friendly_db_error(table, e))

    # Table created → persist the semantic descriptions (data dictionary). Best-effort:
    # a metadata write must never fail a successful table creation.
    await _save_descriptions(state.get("output") or {})

    n = len((state.get("output") or {}).get("columns") or [])
    name = table or "table"
    msg = f"Created the table “{name}” with {n} column{'s' if n != 1 else ''}."
    return {**state, "current_stage": StageType.DONE.value,
            "output": {"type": OUTPUT_EXECUTION, "sql": sql, "message": msg}}


def _route_after_approval(state: AgentState) -> str:
    stage = state.get("current_stage")
    if stage == StageType.EXECUTION.value:
        return "EXECUTION"
    if stage == StageType.SCHEMA_PREVIEW.value:
        return "APPROVAL"  # validation failed → re-open the editor (loop back to interrupt)
    return StageType.DONE.value  # cancelled


def _route_after_execution(state: AgentState) -> str:
    # DB error set the stage back to SCHEMA_PREVIEW → re-open the editor; otherwise done.
    return "APPROVAL" if state.get("current_stage") == StageType.SCHEMA_PREVIEW.value else StageType.DONE.value


async def _done(state: AgentState) -> AgentState:
    return {**state, "current_stage": StageType.DONE.value}


class CreateTableWorkflow:
    def __init__(self):
        self._graph = None

    async def _compiled(self):
        if self._graph is None:
            g = StateGraph(AgentState)
            g.add_node("SCHEMA_PREVIEW", _schema_preview)
            g.add_node("APPROVAL", _approval)
            g.add_node("EXECUTION", _execution)
            g.add_node(StageType.DONE.value, _done)
            g.set_entry_point("SCHEMA_PREVIEW")
            g.add_edge("SCHEMA_PREVIEW", "APPROVAL")
            g.add_conditional_edges("APPROVAL", _route_after_approval,
                                    {"EXECUTION": "EXECUTION", "APPROVAL": "APPROVAL",
                                     StageType.DONE.value: StageType.DONE.value})
            g.add_conditional_edges("EXECUTION", _route_after_execution,
                                    {"APPROVAL": "APPROVAL", StageType.DONE.value: StageType.DONE.value})
            g.add_edge(StageType.DONE.value, END)
            self._graph = g.compile(checkpointer=await get_async_checkpointer())
        return self._graph

    def _cfg(self, session_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": f"{session_id}:create_table"}}

    async def pending(self, session_id: str) -> bool:
        graph = await self._compiled()
        snap = await graph.aget_state(self._cfg(session_id))
        return bool(getattr(snap, "next", None))

    async def run(self, session_id: str, user_message: str, engine: str, *, resume=None) -> tuple[AgentState, bool]:
        graph = await self._compiled()
        cfg = self._cfg(session_id)
        if resume is None:
            await graph.ainvoke(create_initial_state(session_id, user_message, engine), cfg)
        else:
            await graph.ainvoke(Command(resume=resume), cfg)
        snap = await graph.aget_state(cfg)
        state = cast(AgentState, dict(snap.values) if snap and snap.values else {})
        return state, bool(getattr(snap, "next", None))
