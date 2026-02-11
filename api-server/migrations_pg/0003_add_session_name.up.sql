-- Add session_name column (display name from first message or default)
ALTER TABLE session ADD COLUMN IF NOT EXISTS session_name TEXT;

