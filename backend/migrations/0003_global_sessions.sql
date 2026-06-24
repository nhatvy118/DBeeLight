-- Global (project-less) sessions + per-user DB connection.

-- Sessions may be global (not tied to a project).
ALTER TABLE sessions ALTER COLUMN project_id DROP NOT NULL;

-- One active DB connection per user (used by global sessions).
ALTER TABLE users ADD COLUMN IF NOT EXISTS active_db_url TEXT;
