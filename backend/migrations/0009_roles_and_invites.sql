-- 0009: three-role model (admin | technical | viewer) + invite-only access.
--
-- Replaces the is_admin boolean with a role enum:
--   admin     → runs the workspace, manages people & roles
--   technical → builds with data (full read/write) — what existing non-admin users were
--   viewer    → non-technical, read-only, sees only projects shared with them
--
-- Login is invite-only: an admin pre-authorises an email (invites table); the account is
-- created on that person's first Google sign-in (the invite is consumed).

-- 1) role column, backfilled from is_admin (admins → admin, everyone else → technical).
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'technical'
    CHECK (role IN ('admin', 'technical', 'viewer'));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'users' AND column_name = 'is_admin') THEN
        UPDATE users SET role = 'admin' WHERE is_admin;
        ALTER TABLE users DROP COLUMN is_admin;
    END IF;
END $$;

-- 2) invites — emails an admin has pre-authorised. Consumed (deleted) on first login.
CREATE TABLE IF NOT EXISTS invites (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'technical', 'viewer')),
    invited_by  TEXT REFERENCES users(google_sub) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- one pending invite per email (case-insensitive)
CREATE UNIQUE INDEX IF NOT EXISTS uq_invites_email_lower ON invites (lower(email));
