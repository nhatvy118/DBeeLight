-- Cached tabular schema at upload (SQL-first chat context).
ALTER TABLE files ADD COLUMN IF NOT EXISTS schema_snapshot JSONB;
