# DBeeLight

A Natural Language to SQL (NL2SQL) AI agent platform. Users chat in plain language; the system classifies intent, routes to the appropriate workflow, and executes SQL or file operations — with human-in-the-loop approval for any write operations.

## Architecture Overview

```
      User Message
            │
            ▼
┌──────────────────────┐
│  normalize()         │  <- resolve references, translate to English
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  classify()          │  <- LLM intent router (router_model)
└──────────┬───────────┘
           │
     ┌─────┴──────────────────────────────────────┐
     ▼             ▼            ▼         ▼        ▼
db_readonly   db_mutation  db_create   chart    excel
db_general                  _table
     │             │            │         │        │
     ▼             ▼            ▼         ▼        ▼
 Tool loop    LangGraph    LangGraph   Tool loop  Tool loop
 (LLM +       workflow     workflow    (LLM +     (LLM +
  db tools)   + approval   + schema    db tools   Excel MCP
               gate        editor)    + chart     over HTTP)
                                       tools)
```

### Intent Routes

| Route | Triggered by | Backend |
|---|---|---|
| `db_readonly` | SELECT queries — "show", "list", "top N", "how many" | `ReadOnlyWorkflow` (LangGraph) |
| `db_general` | Analysis, schema exploration, multi-query reasoning | Tool loop |
| `db_mutation` | INSERT / UPDATE / DELETE / ALTER — requires user approval | `MutationWorkflow` (LangGraph) |
| `db_create_table` | "Create a table for …" — shows schema editor before executing | `CreateTableWorkflow` (LangGraph) |
| `chart` | "Plot / chart / visualize …" — generates a Vega-Lite spec | Tool loop (chart + db tools) |
| `excel` | Questions about an uploaded Excel file | Tool loop (Excel MCP over HTTP) |
| `off_topic` | Greetings, small talk, anything unrelated | Friendly decline |

### Components

```
DBeeLight/
├── backend/                  # Python 3.12 / FastAPI
│   ├── app/
│   │   ├── agent/
│   │   │   ├── orchestration/   # intent classifier + orchestrator (singleton)
│   │   │   ├── graph/           # LangGraph workflows (readonly / mutation / create_table)
│   │   │   ├── tools/           # in-process db tools, chart tools, Excel HTTP backend
│   │   │   └── loop.py          # generic tool loop for db_general / chart / excel routes
│   │   └── features/            # REST API modules: auth, chat, sessions, projects,
│   │                            #                   files, charts, admin, metadata
│   └── excel_server/         # FastMCP Excel server (HTTP, port 8931)
├── frontend/                 # React 18 + TypeScript + Vite + Tailwind
│   └── src/
└── docker-compose.yml        # postgres + excel-server + backend
```

### Human-in-the-loop (Write Operations)

Mutation and create-table routes pause before executing:

- **`db_mutation`** - generates SQL, shows a preview of affected rows, waits for user to click "Execute".
- **`db_create_table`** - generates a column schema in a structured editor; user can edit columns before confirming.

The `Orchestrator.resume()` method handles confirmation (or cancellation) for both. Pending actions are tracked in the database so page reloads don't lose state.

---

## Services

| Service | Port | Description |
|---|---|---|
| Backend API | 5001 | FastAPI, auto-runs migrations on startup |
| Excel MCP server | 8931 | FastMCP HTTP server for Excel file operations |
| PostgreSQL | 5432 | pgvector/pgvector:pg16 |
| Frontend (dev) | 5173 | Vite dev server |

---

## Running the Project

See **HuongDanCaiDat.txt** for prerequisites and environment setup, and **HuongDanSuDung.txt** for step-by-step run instructions (Docker Compose or local development).

Quick start with Docker:

```bash
# 1. Set up .env files (see HuongDanCaiDat.txt)
cp .env.example .env
cp backend/.env.example backend/.env
# edit both files — set POSTGRES_PASSWORD and OPENAI_API_KEY at minimum

# 2. Start backend stack
docker compose up --build

# 3. Start frontend (separate terminal)
cd frontend && npm run dev
```

App is at http://localhost:5173. API docs at http://localhost:5001/docs.

---

## Environment Variables (backend/.env)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `OPENAI_API_KEY` | Yes | Used by both LLM and intent router |
| `LLM_MODEL` | Yes | Main model (e.g. `gpt-5.2`) |
| `ROUTER_MODEL` | Yes | Model for intent classification (e.g. `gpt-5.2`) |
| `EXCEL_MCP_URL` | Yes | URL of the Excel MCP server (`http://localhost:8931/mcp`) |
| `SESSION_SECRET` | Yes | Random string for session signing |
| `GOOGLE_CLIENT_ID` | No | Google OAuth (optional — app works without it) |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth |
| `BOOTSTRAP_ADMIN_EMAILS` | No | Comma-separated emails that are auto-granted admin on first login |
| `RESEND_API_KEY` | No | Email invitations (omit to disable email, sharing via link still works) |
| `FRONTEND_URL` | No | Used in CORS and OAuth redirect (default: `http://localhost:5173`) |
