-- Saved charts → a project's dashboard. One dashboard per project = all saved_charts
-- with that project_id. We store the chart RECIPE (sql + mark + encoding), not the data,
-- so the dashboard re-runs the SQL on view (live data). SQL is read-only (DQL), enforced
-- in the service layer on both save and render.

CREATE TABLE IF NOT EXISTS saved_charts (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    sql         TEXT NOT NULL,
    mark        TEXT NOT NULL,
    encoding    TEXT NOT NULL,          -- JSON string (vega-lite encoding)
    transform   TEXT,                   -- JSON string (optional vega-lite transforms)
    layout      TEXT,                   -- 'full' | 'half' | NULL
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saved_charts_project ON saved_charts(project_id);
