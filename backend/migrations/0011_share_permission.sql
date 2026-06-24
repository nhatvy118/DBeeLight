-- 0011: per-share access level. A share can be 'view' (read-only) or 'edit' (read + write).
-- EDIT is only honoured for technical recipients — viewers are always read-only regardless,
-- enforced in app code (chat._can_edit checks role AND permission). Default is the safe 'view'.

ALTER TABLE project_shares ADD COLUMN IF NOT EXISTS permission TEXT NOT NULL DEFAULT 'view'
    CHECK (permission IN ('view', 'edit'));
