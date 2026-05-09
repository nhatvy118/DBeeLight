# chart-server

MCP server that turns a SQL query + chart configuration into a Vega-Lite v5 spec.

## How it works

```
LLM tool call:    generate_line_chart(sql="SELECT ...", x_field=..., y_field=...)
                                     │
                                     ▼
chart-server:     execute SQL against the active project DB
                  → fetch rows (Python only — never returned to LLM)
                  → assemble Vega-Lite v5 spec
                  → return spec JSON as the tool result
                                     │
                                     ▼
LLM context:      receives spec JSON (a few KB) — not the rows
Frontend:         renders <VegaLite spec={…} /> from the spec
```

## Isolation

`db_url` is **injected by the orchestrator** from validated session state, not chosen
by the LLM. The agent's view of these tools does not include `db_url` in any meaningful
way — the orchestrator overwrites that parameter on every call.

Defense in depth: `_validate_db_url` rejects schemes outside (`sqlite`, `postgresql`)
and SQLite paths outside the configured `CHART_SQLITE_ALLOWED_DIRS`.

## Environment

- `CHART_SQLITE_ALLOWED_DIRS` — colon-separated allow-list of directories under which
  SQLite files may live. Default: `/app/databases`.
- `CHART_MAX_ROWS` — soft cap on rows fetched per chart query (default 100000).
  Vega-Lite render performance degrades sharply past this in browsers.

## Tools

| Tool | Vega-Lite mark | Required fields |
|---|---|---|
| `generate_line_chart` | line | x_field, y_field |
| `generate_bar_chart` | bar | x_field, y_field |
| `generate_pie_chart` | arc | category_field, value_field |
| `generate_scatter_chart` | point | x_field, y_field |
| `generate_heatmap` | rect | x_field, y_field, value_field |
| `generate_histogram` | bar (binned) | x_field |
| `generate_area_chart` | area | x_field, y_field |
| `generate_boxplot` | boxplot | x_field, y_field |
| `render_vega_lite_spec` | any | spec_template (escape hatch) |
