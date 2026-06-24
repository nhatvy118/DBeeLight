-- Remove the chat-sharing feature: drop the share tables and the forked-session column.
-- Forked sessions (created when a recipient accepted a share) are deleted along with their
-- messages/files (per ON DELETE CASCADE). Idempotent: guarded with IF EXISTS so re-running is safe.
--
-- NOTE: the `files` table (also created in 0002_shares_and_files.sql) is NOT share-related and is kept.

-- Delete forked sessions first, while the column still exists (skips cleanly on re-run).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'sessions' AND column_name = 'share_recipient_id'
    ) THEN
        DELETE FROM sessions WHERE share_recipient_id IS NOT NULL;
    END IF;
END $$;

-- Drop the share tables (recipients references shares → drop it first).
DROP TABLE IF EXISTS chat_share_recipients;
DROP TABLE IF EXISTS chat_shares;

-- Drop the forked-session marker column from sessions.
ALTER TABLE sessions DROP COLUMN IF EXISTS share_recipient_id;
