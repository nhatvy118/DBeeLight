# Excel Server

Stdio adapter for [`excel-mcp-server`](https://github.com/haris-musa/excel-mcp-server) (MIT, Haris Musa).

Replaces the previous `excel-summary/` server. The agent now uses this for all
spreadsheet manipulation tools (workbook/worksheet/range ops, formulas,
formatting, charts, pivot tables, native Excel tables).

## Install

```bash
cd excel-server
uv sync
```

This installs `excel-mcp-server>=0.1.8` into `excel-server/.venv/`. The agent
auto-detects this venv when launching the server (see
`base_agent.connect_to_server`).

## How the agent invokes it

`agent_repository.py` registers `excel-server/excel_server.py` for the
`excel` agent. On each session boot, the agent spawns:

```
excel-server/.venv/bin/python excel-server/excel_server.py
```

which calls `run_stdio()` from `excel_mcp.server`.

## Tool reference

See [TOOLS.md in upstream](https://github.com/haris-musa/excel-mcp-server/blob/main/TOOLS.md).

Tool families exposed:
- Workbook ops: `create_workbook`, `create_worksheet`, `get_workbook_metadata`
- Data I/O: `read_data_from_excel`, `write_data_to_excel`
- Worksheet: `copy_worksheet`, `delete_worksheet`, `rename_worksheet`
- Range: `copy_range`, `delete_range`, `validate_excel_range`, `get_data_validation_info`
- Row/Col: `insert_rows`, `insert_columns`, `delete_sheet_rows`, `delete_sheet_columns`
- Formula: `apply_formula`, `validate_formula_syntax`
- Format: `format_range`, `merge_cells`, `unmerge_cells`, `get_merged_cells`
- Chart: `create_chart`
- Pivot: `create_pivot_table`
- Table: `create_table`

## File path scoping

In stdio mode, `EXCEL_FILES_PATH` is not required — the server accepts
absolute paths. The frontend's upload flow already passes absolute paths
to the agent via `[UPLOADED_EXCEL_PATH_*]` markers, so no further changes
are needed.
