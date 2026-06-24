-- Schema metadata app (Postgres). KHÔNG chứa dữ liệu user — cái đó nằm ở project DB.

CREATE TABLE IF NOT EXISTS users (
    google_sub  TEXT PRIMARY KEY,
    id          BIGSERIAL UNIQUE,          -- id số (dùng cho admin endpoints / FE)
    email       TEXT NOT NULL,
    name        TEXT DEFAULT '',
    is_admin    BOOLEAN NOT NULL DEFAULT false,
    disabled_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    user_id     TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    db_url      TEXT NOT NULL DEFAULT 'placeholder://not-configured',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title              TEXT DEFAULT 'New chat',
    share_recipient_id TEXT,               -- != NULL nếu là session fork từ share
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_project ON sessions(user_id, project_id);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    tool_events JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
