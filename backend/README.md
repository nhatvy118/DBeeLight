# DBeeLight Backend (kiến trúc mới)

Backend viết lại theo `docs/design.md`:

- **database, chart** = tool **in-process** (gọi hàm trực tiếp, connection qua `ContextVar`).
- **excel** = MCP server riêng, giao tiếp **HTTP** (`streamable-http`).
- **Orchestrator** = singleton; **không** spawn subprocess per-user, **không** LRU.
- Connection pool theo `project_id` nằm trong backend; LLM không thấy DSN.

## Cấu trúc

```
backend/
  app/
    main.py                 # FastAPI + lifespan (dựng pool + orchestrator singleton)
    config.py               # settings (env)
    db.py                   # asyncpg pool cho metadata app
    agent/                  # LÕI redesign
      context.py            # RequestContext + DbContext + current_ctx (ContextVar)
      pool.py               # ConnectionPool[project_id] -> adapter
      llm.py                # OpenAI client
      loop.py               # tool-loop per-request (không giữ state instance)
      summarization.py      # tóm tắt hội thoại dài (lean, không cần langmem)
      adapters/             # base / sqlite / postgres / factory
      tools/                # registry, db_tools, chart_tools, backends
      orchestration/        # intent, orchestrator (singleton)
      graph/                # LangGraph: checkpointer + sql_verification +
                            #   readonly/mutation/create_table workflows
    features/               # auth, projects, sessions, chat, share, files
  migrations/               # SQL Postgres

> **Python >= 3.11 bắt buộc** cho async LangGraph interrupt (mutation/create_table
> approval). Target là 3.12. (Trên 3.10 async interrupt không chạy do contextvar.)
```

## Chạy (dev)

```bash
cd backend
cp .env.example .env          # điền OPENAI_API_KEY, DATABASE_URL...
uv sync                       # hoặc: pip install -e .
# Postgres metadata + migrations
psql "$DATABASE_URL" -f migrations/0001_init.sql
# Excel MCP server (terminal riêng)
python -m excel_server        # hoặc docker compose up excel-server
# API
uvicorn app.main:app --reload --port 8000
```

Hoặc toàn bộ: `docker compose up`.

## Tests / đã verify

```bash
PYTHONPATH=. python3 tests/smoke_core.py      # 13/13: adapter, ContextVar inject, redact DSN,
                                              #        schema không lộ adapter, cô lập 2 user
PYTHONPATH=. python3 tests/smoke_files.py     # 5/5: file→session SQLite (t_)→query, allowed_tables
PYTHONPATH=. python3 tests/smoke_mutation.py  # 12/12: sql_verification + node mutation workflow
```

Đã verify trong sandbox (không cần Postgres/OpenAI):
- Lõi tool in-process + ContextVar + redact DSN + cô lập đồng thời (smoke_core 13/13)
- File upload → session SQLite (`t_`) → query qua session adapter + lọc bảng (smoke_files 5/5)
- App boot + 16 routes + auth gate 401
- Excel HTTP: excel-server `streamable-http` thật → `ExcelHttpBackend` list 25 tool + `create_workbook` qua HTTP tạo file ✓

Cần creds bên ngoài (chưa chạy trong sandbox):
- Luồng metadata đầy đủ (auth→project→session→lưu lịch sử): cần **Postgres**.
- Vòng intent/tool-loop thật: cần **OPENAI_API_KEY**.

## Khác biệt cốt lõi so với bản cũ

| | Cũ (`api-server` + `mcp-client`) | Mới (`backend/`) |
|---|---|---|
| db/chart tool | MCP subprocess (stdio), spawn per-user | hàm in-process, 1 process |
| connection | global trong subprocess, swap mỗi turn | `ContextVar` per-request + pool theo project |
| orchestrator | per-user + LRU eviction | singleton |
| excel | MCP stdio | MCP HTTP (service riêng) |
| đa user đồng thời | nhờ user-lock tuần tự | cô lập per-request (ContextVar/local) |
