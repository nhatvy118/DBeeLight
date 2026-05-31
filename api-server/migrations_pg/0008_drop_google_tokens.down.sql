-- Re-add the per-user Google OAuth token columns (mirror of 0005 up).

ALTER TABLE users ADD COLUMN IF NOT EXISTS google_access_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_refresh_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_token_expires_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_token_scope TEXT;
