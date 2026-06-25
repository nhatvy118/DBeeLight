-- 0014: drop the Q&A file columns.
-- The Q&A import path (uploading a file into a per-session SQLite sandbox) was removed — files are
-- now either imported into the project DB (no `files` row) or kept as Excel workbooks (disk_path).
-- The columns that tracked the session SQLite DB + table for a Q&A file are now always NULL → drop.
ALTER TABLE files DROP COLUMN IF EXISTS sqlite_db_path;
ALTER TABLE files DROP COLUMN IF EXISTS table_name;
