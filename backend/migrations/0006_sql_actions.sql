-- Per-session record of which gated SQL actions were executed / cancelled, so the
-- Execute button state survives a history reload (the FE keys this by a stable action_id).

CREATE TABLE IF NOT EXISTS sql_actions (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    action_id  TEXT NOT NULL,
    state      TEXT NOT NULL,          -- 'executed' | 'cancelled' | 'failed'
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, action_id)
);
