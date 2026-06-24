-- Semantic data dictionary: human/LLM-written meaning of tables & columns in the user's
-- databases, so the SQL-generating agent can write accurate queries. Stores metadata only
-- (no user data). Database-level context comes from projects.description, not here.
--
-- Scope identifies WHICH database a row describes:
--   ('project', <project_id>)        → an app project's DB
--   ('project', 'user:<user_id>')    → the user's external (per-user) connection
--   ('file',    <file_id>)           → an uploaded file's tables (reserved; not used yet)
--
-- Levels (within a scope):
--   table_name set, column_name NULL → table-level description
--   table_name set, column_name set  → column-level description

CREATE TABLE IF NOT EXISTS descriptions (
    id           BIGSERIAL PRIMARY KEY,
    scope_type   TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    table_name   TEXT NOT NULL,            -- normalized lowercase
    column_name  TEXT,                     -- NULL = table-level; set = column-level (lowercase)
    description  TEXT NOT NULL,
    enum_values  JSONB,                    -- optional: valid values for a coded column
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One description per (scope, table, column); COALESCE so the NULL column_name (table-level)
-- still participates in uniqueness and can be upserted via ON CONFLICT.
CREATE UNIQUE INDEX IF NOT EXISTS descriptions_key
    ON descriptions (scope_type, scope_id, table_name, COALESCE(column_name, ''));
