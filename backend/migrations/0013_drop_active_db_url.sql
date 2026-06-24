-- 0013: drop users.active_db_url — the per-user "global connection" is gone.
-- External databases are now modelled as external projects (projects.kind='external', db_url=DSN),
-- so a single per-user active connection no longer exists. No code reads this column after the
-- external-as-project unification (Phase 2). Pre-deploy: nothing to preserve.

ALTER TABLE users DROP COLUMN IF EXISTS active_db_url;
