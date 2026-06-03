-- Admin dashboard: role + account disable flags on users.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin) WHERE is_admin;

-- Bootstrap the first admin manually after migrating, e.g.:
--   UPDATE users SET is_admin = true WHERE email = 'you@example.com';
