-- Share chat session feature.
-- Two tables: chat_shares (one per share event) + chat_share_recipients (one per recipient).
-- Also: users.email so owners can target recipients by email,
--       session.share_recipient_id so the chat pipeline can gate writes by permission.

-- 1) Add email to users (populated on next Google OAuth login).
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 2) Add share_recipient_id to session. FK is added after chat_share_recipients exists.
ALTER TABLE session ADD COLUMN IF NOT EXISTS share_recipient_id UUID;

-- 3) chat_shares: one row per "share event" by an owner.
CREATE TABLE IF NOT EXISTS chat_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_shares_owner ON chat_shares(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_chat_shares_session ON chat_shares(session_id);

-- 4) chat_share_recipients: one row per (share, recipient) pair.
CREATE TABLE IF NOT EXISTS chat_share_recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_id UUID NOT NULL REFERENCES chat_shares(id) ON DELETE CASCADE,
    recipient_email TEXT NOT NULL,
    recipient_user_id TEXT REFERENCES users(google_sub) ON DELETE SET NULL,
    permission TEXT NOT NULL CHECK (permission IN ('view_only', 'read_data', 'edit_data')),
    accept_token TEXT NOT NULL UNIQUE,
    forked_session_id TEXT REFERENCES session(id) ON DELETE SET NULL,
    accepted_at TIMESTAMP,
    revoked_at TIMESTAMP,
    UNIQUE (share_id, recipient_email)
);
CREATE INDEX IF NOT EXISTS idx_chat_share_recipients_token ON chat_share_recipients(accept_token);
CREATE INDEX IF NOT EXISTS idx_chat_share_recipients_email ON chat_share_recipients(recipient_email);
CREATE INDEX IF NOT EXISTS idx_chat_share_recipients_user ON chat_share_recipients(recipient_user_id);

-- 5) Now wire session.share_recipient_id → chat_share_recipients.id.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_session_share_recipient'
    ) THEN
        ALTER TABLE session
            ADD CONSTRAINT fk_session_share_recipient
            FOREIGN KEY (share_recipient_id)
            REFERENCES chat_share_recipients(id)
            ON DELETE SET NULL;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_session_share_recipient ON session(share_recipient_id);
