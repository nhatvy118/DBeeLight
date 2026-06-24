-- 0012: project kind — distinguishes LightDBee-hosted (internal, sqlite) projects from
-- projects connected to a user's own external database (external, postgres DSN).
-- Drives the FE "External" badge, the create flow (internal auto-provisions a SQLite file;
-- external takes a DSN + connection probe), and the "Edit connection" action (external only).
-- We store kind explicitly rather than inferring from the db_url scheme so an external project
-- that hasn't connected yet (db_url still the placeholder) is still known to be external.
--
-- Pre-deploy: no live data to migrate. Every existing project is sqlite-backed → default 'internal'
-- backfills them correctly. External-DB-as-project creation lands in a later phase.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'internal'
    CHECK (kind IN ('internal', 'external'));
