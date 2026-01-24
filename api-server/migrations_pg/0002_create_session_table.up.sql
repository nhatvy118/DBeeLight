CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    content JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS session_user_id_idx ON session (user_id);
