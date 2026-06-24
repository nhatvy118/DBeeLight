-- disk_path is only set for files saved on disk (Excel-edit mode). Q&A and project-db
-- imports keep no original file, so disk_path must be nullable.
ALTER TABLE files ALTER COLUMN disk_path DROP NOT NULL;
