# MCP Server Projects

Dự án này chứa các MCP (Model Context Protocol) servers và client để tương tác với chúng.

## Các Servers

### 1. Database Server (`database/`)
MCP server cung cấp các công cụ để thao tác với PostgreSQL database (CRUD, schema management, SQL execution, etc.).

**Cài đặt:**
```bash
cd database
uv sync  # Tạo .venv và cài đặt dependencies
```

**Lưu ý:** Không cần file `.env` nữa! Bạn sẽ cung cấp thông tin database qua chatbot.

**Sử dụng:**
- Database server được kết nối bởi `api-server` thông qua package `mcp_agent`.
- Hãy chạy `api-server` và gọi các endpoint `/api/chat` để sử dụng.

**Tools:** connect_db, create_db_from_spec, list_databases, list_tables, get_table_stats, get_schema, generate_schema_doc, manage_constraint, manage_trigger, preview_table, validate_sql, explain_sql, run_mutation, và các tools CRUD cơ bản.

Client sẽ tự động sử dụng Python từ `.venv` của database server để đảm bảo tất cả dependencies đã được cài đặt.

### 2. Excel Server (`excel-server/`)
Stdio adapter cho [`excel-mcp-server`](https://github.com/haris-musa/excel-mcp-server) (haris-musa, MIT). Cung cấp tool thao tác file Excel: workbook/worksheet ops, đọc/ghi cell, formula, formatting, chart, pivot table, native Excel tables.

**Cài đặt:**
```bash
cd excel-server
uv sync  # Tạo .venv và cài đặt excel-mcp-server
```

**Sử dụng:**
- Excel server được kết nối bởi `api-server` thông qua package `mcp_agent`.
- Hãy chạy `api-server` và gọi các endpoint `/api/chat` để sử dụng.

**Tools (24):** create_workbook, create_worksheet, get_workbook_metadata, read_data_from_excel, write_data_to_excel, copy_worksheet, delete_worksheet, rename_worksheet, copy_range, delete_range, validate_excel_range, get_data_validation_info, insert_rows, insert_columns, delete_sheet_rows, delete_sheet_columns, apply_formula, validate_formula_syntax, format_range, merge_cells, unmerge_cells, get_merged_cells, create_chart, create_pivot_table, create_table.

### 2b. Google Sheets Server (`gsheets-server/`)
Per-user Google Sheets / Drive read access. Mỗi user app login Google → tokens (access + refresh) được lưu encrypted vào `users` table → server này dùng để đọc Sheets thay user.

**Cài đặt:**
```bash
cd gsheets-server
uv sync
```

**Yêu cầu env (trong `api-server/.env`):**
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (đã có cho login)
- `TOKEN_ENCRYPTION_KEY`: Fernet key — generate bằng `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Dev có thể bỏ qua (token lưu plaintext + log warning).

**Tools (2):** `get_spreadsheet_info`, `read_google_sheet`. Read-only. User phải paste URL/ID của sheet (không có Drive search vì cố tình tránh `drive.readonly` restricted scope).

**Lưu ý:** User đã login từ trước phải logout + login lại để consent thêm Sheets scope.

### 3. Excel UI (`excel-ui/`)
Web UI để upload Excel files và thao tác workbook qua MCP excel-server tools.

**Cài đặt:**
```bash
cd excel-ui
uv sync
```

**Sử dụng:**
```bash
cd excel-ui
uv run app.py
```

Sau đó mở browser tại: http://localhost:5000

**Tính năng:**
- Upload Excel files (drag & drop hoặc click)
- Data preview
- Generate summary với statistics
- Generate charts (bar, line, pie, scatter, histogram)
- Chart type suggestions

## MCP Client (`mcp-client/`)

Client để kết nối và tương tác với các MCP servers sử dụng OpenAI GPT.

**Cài đặt:**
```bash
cd mcp-client
uv sync  # Tạo .venv và cài đặt dependencies
```

**Yêu cầu:**
- File `.env` với `OPENAI_API_KEY`

**Sử dụng:**
- `mcp-client` chỉ là package/library (không còn CLI).
- Được dùng bởi `api-server` để cung cấp REST API.

**Kiến trúc (Hybrid Orchestrator):**

```
User Prompt
      │
      ▼
┌──────────────────┐
│  IntentRouter    │  ← LLM classify: simple/complex/conversational
│  .classify()     │
└────────┬─────────┘
         │
    ┌────┴────┬────────────┐
    ▼         ▼            ▼
Simple   Complex    Conversational
    │         │            │
    ▼         ▼            ▼
LLM-driven  Workflow   Continue
(BaseAgent)  (LangGraph) conversation
```

**Hybrid Approach:**
- **Simple queries** ("list tables", "show schema", "select data"): Dùng LLM-driven (BaseAgent) - nhanh, trực tiếp
- **Complex queries** ("insert data", "create report"): Dùng LangGraph workflow - sequential stages + human approval
- **Conversational**: Tiếp tục conversation với context

**LangGraph Workflow:**
- Mỗi agent (database, excel) có workflow riêng
- Nodes delegate cho BaseAgent để execute tools
- Hỗ trợ human-in-the-loop (chờ user approve SQL)

**Lưu ý về Virtual Environment:**
- Client tự động phát hiện và sử dụng Python từ `.venv` của server (nếu có)
- Điều này đảm bảo server chạy với đúng dependencies đã được cài đặt
- Nếu không tìm thấy venv, client sẽ fallback về system Python

Xem thêm chi tiết trong các README của từng server.