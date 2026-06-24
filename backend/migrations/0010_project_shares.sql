-- 0010: project sharing — a technical owner grants a (non-technical) user READ access to a
-- project's data. Sharing shares the DATA, not the owner's chats. Viewers see only projects
-- shared with them and can never change data (enforced server-side in chat).

CREATE TABLE IF NOT EXISTS project_shares (
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,  -- the person it's shared with
    shared_by   TEXT REFERENCES users(google_sub) ON DELETE SET NULL,           -- who shared it
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id)
);

-- fast "what's shared with me" lookup
CREATE INDEX IF NOT EXISTS idx_project_shares_user ON project_shares (user_id);
