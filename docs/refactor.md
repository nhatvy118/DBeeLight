Đã đủ thông tin. Đây là toàn cảnh:

---

## Cấu trúc và lưu trữ của app

### Tổng quan các thành phần

```
mcp-server/
├── api-server/          ← FastAPI backend
├── mcp-client/          ← AI engine (mcp_agent package + MCP servers)
└── frontend/            ← React UI
```

---

### 1. Lưu trữ (Storage layers)

App dùng **3 tầng lưu trữ** với mục đích khác nhau:

#### PostgreSQL — dữ liệu bền vững (source of truth)

| Bảng | Lưu gì |
|------|--------|
| `users` | Google OAuth account (`google_sub`, email) |
| `projects` | Project metadata + đường dẫn SQLite DB (`db_url`) |
| `session` | Mỗi chat session — `content JSONB` chứa toàn bộ message history cho UI |
| `chat_shares` | Sự kiện share của owner |
| `chat_share_recipients` | Người được share, permission, forked session |
| `files` | File upload metadata (path, mime type, sqlite table) |
| ~~`file_chunks`~~ | Đã gỡ (RAG/pgvector); tabular dùng SQLite + schema trong prompt |

`session.content` có dạng:
```json
{
  "messages": [
    {"role": "user", "content": "...", "timestamp": "..."},
    {"role": "assistant", "content": "...", "timestamp": "..."}
  ]
}
```
Đây là nguồn dữ liệu UI đọc khi reload trang. Sau refactor, history chỉ được **append** (thêm turn mới) — không bao giờ overwrite từ LangGraph checkpoint.

#### Redis — write buffer tạm thời

`SessionManager` push message mới vào Redis list `{user_id}:{session_id}:stack` trước, flush về PostgreSQL khi stack đạt 20 messages hoặc khi explicit `flush()`. Mục đích: giảm số lần write PostgreSQL. Khi đọc history, data được merge từ cả DB + Redis stack.

#### LangGraph Checkpoint (PostgreSQL hoặc MemorySaver)

LangGraph lưu graph state (message list của `MessagesState`) vào PostgreSQL qua `AsyncPostgresSaver` (nếu có `LANGGRAPH_CHECKPOINT_DB_URL`) hoặc in-memory. Đây là bộ nhớ của agent cho **summarization và context window** — **không phải** lịch sử chat hiển thị UI. Sau summarization, checkpoint chỉ còn messages gần nhất + running summary, không có full history.

#### SQLite — dữ liệu project

Mỗi project có 1 file `.db` SQLite tại `api-server/internal/databases/`. Đây là database người dùng chat về (query, tạo bảng, v.v.).

---

### 2. Cấu trúc code

#### `api-server/internal/features/` — Feature-based layout

```
chat/        router → service → repository (AgentRepository)
auth/        Google OAuth, token crypto
sessions/    List/export sessions
share/       Share + fork sessions
project/     CRUD projects
file/        Upload, chunk, embed files
```

Mỗi feature có: `router.py` (HTTP), `service.py` (business logic), `repository.py` (DB), `schema.py` (Pydantic models).

#### `mcp-client/mcp_agent/` — AI Engine

```
agents/          DatabaseAgent, ExcelAgent, ChartAgent (kế thừa BaseAgent)
orchestration/   Orchestrator (LangGraph) + IntentService (phân loại query)
graph/           chat_graph.py (outer graph), workflows (readonly/mutation/create_table)
session/         SessionManager (write buffer + Postgres persistence)
servers.py       Path resolution cho 4 MCP server subprocesses
```

#### `mcp-client/servers/` — MCP Servers (subprocess)

3 server chạy độc lập, mỗi cái có venv riêng:
- `database/` — kết nối SQLite/PostgreSQL, thực thi SQL
- `excel-server/` — đọc/ghi file Excel
- `chart-server/` — render Vega-Lite charts

---

### 3. Flow một chat message (sau refactor)

```
HTTP POST /chat
  → ChatService.chat()
      → classify_intent()           [1 LLM call, dùng cho permission gate + RAG routing]
      → inject RAG context nếu cần
      → chat_graph.ainvoke()        [outer LangGraph graph]
            → summarize nếu cần
            → orchestrate_node()
                  → Orchestrator.process_query()   [inner LangGraph graph]
                        → _parse_intent_node()     [reuse pre_classified_intent, skip LLM]
                        → route → agent workflow
      → session_manager.add_message("user", ...)    [append vào Redis/JSONB]
      → session_manager.add_message("assistant", .) [append vào Redis/JSONB]
```