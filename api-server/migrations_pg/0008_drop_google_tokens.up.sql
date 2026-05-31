-- Google Sheets integration was removed, so the per-user Google OAuth token
-- columns added in 0005 are no longer used. Drop them.

ALTER TABLE users DROP COLUMN IF EXISTS google_token_scope;
ALTER TABLE users DROP COLUMN IF EXISTS google_token_expires_at;
ALTER TABLE users DROP COLUMN IF EXISTS google_refresh_token;
ALTER TABLE users DROP COLUMN IF EXISTS google_access_token;
