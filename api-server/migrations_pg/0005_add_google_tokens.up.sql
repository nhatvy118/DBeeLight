-- Per-user Google OAuth tokens for Drive / Sheets API access.
-- ``access_token`` / ``refresh_token`` are encrypted at rest via Fernet
-- (see internal/utils/token_crypto.py). ``expires_at`` is the absolute
-- expiry of the access_token (refresh proactively when within ~60s).

ALTER TABLE users ADD COLUMN IF NOT EXISTS google_access_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_refresh_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_token_expires_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_token_scope TEXT;
