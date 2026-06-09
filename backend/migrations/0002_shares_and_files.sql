-- Chia sẻ chat (đầy đủ: token + email + fork) + file upload.

CREATE TABLE IF NOT EXISTS chat_shares (
    id            TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL,
    revoked_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_shares_owner ON chat_shares(owner_user_id);

CREATE TABLE IF NOT EXISTS chat_share_recipients (
    id                 TEXT PRIMARY KEY,
    share_id           TEXT NOT NULL REFERENCES chat_shares(id) ON DELETE CASCADE,
    recipient_email    TEXT NOT NULL,
    permission         TEXT NOT NULL,            -- view_only | read_data | edit_data
    accept_token       TEXT NOT NULL UNIQUE,
    recipient_user_id  TEXT,                     -- google_sub khi đã accept
    forked_session_id  TEXT,                     -- session bản fork của recipient
    accepted_at        TIMESTAMPTZ,
    revoked_at         TIMESTAMPTZ,
    email_sent_at      TIMESTAMPTZ,
    email_error        TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_share_recipients_email ON chat_share_recipients(lower(recipient_email));
CREATE INDEX IF NOT EXISTS idx_share_recipients_token ON chat_share_recipients(accept_token);

CREATE TABLE IF NOT EXISTS files (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    disk_path       TEXT NOT NULL,
    sqlite_db_path  TEXT,
    table_name      TEXT,
    size_bytes      BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id);
