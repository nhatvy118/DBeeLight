ALTER TABLE session DROP CONSTRAINT IF EXISTS fk_session_share_recipient;
DROP INDEX IF EXISTS idx_session_share_recipient;
ALTER TABLE session DROP COLUMN IF EXISTS share_recipient_id;

DROP TABLE IF EXISTS chat_share_recipients;
DROP TABLE IF EXISTS chat_shares;

DROP INDEX IF EXISTS idx_users_email;
ALTER TABLE users DROP COLUMN IF EXISTS email;
