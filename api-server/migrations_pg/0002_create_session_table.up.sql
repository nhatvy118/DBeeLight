CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    content JSONB NOT NULL,
    project_id UUID REFERENCES projects(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS session_user_id_idx ON session (user_id);
CREATE INDEX IF NOT EXISTS session_project_id_idx ON session (project_id);
CREATE INDEX IF NOT EXISTS session_user_id_project_id_idx ON session (user_id, project_id);
