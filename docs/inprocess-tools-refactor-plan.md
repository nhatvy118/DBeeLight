# Refactor plan: in-process tools (database/chart) + Excel qua HTTP MCP

> Mục tiêu: bỏ kiến trúc spawn-MCP-subprocess-per-user. Database và Chart là code
> của chính dự án → gọi tool **trực tiếp trong process** api-server. Chỉ **Excel**
> (wrapper quanh `haris-musa/excel-mcp-server`, bên thứ ba) giữ dạng **MCP server
> riêng, giao tiếp HTTP**.

## 1. Quyết định đã chốt

- **database, chart**: không còn là MCP server. Chuyển adapter/tool thành **thư viện
  Python** gọi trực tiếp từ orchestrator (cùng process api-server).
- **excel**: là MCP server **standalone**, transport **streamable-http**, agent nối
  bằng `streamablehttp_client(url)` thay vì spawn stdio.
- **Orchestrator**: trở thành **singleton** (1 instance toàn app), bỏ cache per-user,
  bỏ LRU eviction, bỏ spawn subprocess.
- **Connection DB của user**: pool nằm **trong api-server**, key theo `project_id`.
  Credential ở api-server; LLM không thấy URL (tiêm qua tham số/ContextVar, không qua
  tool arguments; tool result phải redact).

## 2. Kiến trúc đích

```
                    ┌────────────────── api-server (process, scale ngang được) ──────────────────┐
 Frontend ─HTTP───► │ FastAPI router + auth                                                        │
 "Connect DB" form ►│ CONTROL: check ownership project → lưu projects.db_url (mã hoá nếu PG ngoài) │
                    │ ConnectionPool[project_id] → adapter (postgres/sqlite)   ◄── credential ở đây │
                    │                                                                               │
 chat message ────► │ Orchestrator (SINGLETON)                                                      │
                    │   set ContextVar current_db_ctx = pool_for(project, session_file)             │
                    │   LangGraph workflows (readonly/create/mutation) + LLM tool-loop              │
                    │     ├── InProcessBackend ──► db_tools.* / chart_tools.*  (GỌI HÀM TRỰC TIẾP)  │
                    │     │        └─ đọc adapter từ ContextVar → chạy SQL ngay trong process        │
                    │     └── ExcelHttpBackend ──HTTP (MCP streamable-http)──┐                       │
                    └────────────────────────────────────────────────────────┼──────────────────────┘
                                                                              ▼
                                                              excel-server (process riêng, HTTP)
                                                              wrapper haris-musa/excel-mcp-server
                                                              ⇅ shared volume chứa .xlsx
   App metadata (users / projects / sessions / chat history) ─► Postgres  (api-server._db_pool, giữ nguyên)
   Project data DB ─► SQLite files (shared volume)  HOẶC  Postgres-per-project (xem §7)
```

**Ranh giới tầm nhìn LLM:** LLM chỉ thấy `{tool, arguments}` + tool result (đã redact).
`db_url`/DSN không bao giờ nằm trong context của LLM — nó là object Python tiêm vào
lời gọi hàm, hoặc DSN ở header khi nói chuyện với excel-server.

## 3. Nguyên tắc then chốt

### 3.1 ContextVar thay cho module-global (giải quyết race + multi-project)
Hiện `database.py` giữ `_primary_adapter`/`_session_adapter` là **module-global** →
mỗi user một subprocess, và phải swap global mỗi turn → có race khi 1 user mở 2 project.

Thay bằng `contextvars.ContextVar` (task-local theo async request):
```python
# mcp_agent/tools/context.py
from dataclasses import dataclass
from contextvars import ContextVar

@dataclass
class DbContext:
    primary: "DatabaseAdapter | None" = None      # DB của project
    session: "DatabaseAdapter | None" = None      # SQLite của file upload trong session
    allowed_tables: set[str] | None = None

current_db_ctx: ContextVar[DbContext] = ContextVar("current_db_ctx")
```
Tool đọc adapter từ ContextVar, không từ global → 2 request đồng thời cho 2 project
**không đụng nhau** (ContextVar tách theo task), hết race.

### 3.2 Tool backend trừu tượng (giữ workflow gần như nguyên vẹn)
LangGraph workflow đang gọi `_call_tool(agent, name, args)`. Định nghĩa một interface
chung để workflow không cần biết tool chạy in-process hay qua HTTP:
```python
class ToolBackend(Protocol):
    def list_tools_openai(self) -> list[dict]: ...
    async def call_tool(self, name: str, args: dict) -> ToolResult: ...
```
- `InProcessBackend`: registry tên→hàm cho db_tools/chart_tools; `call_tool` dispatch
  thẳng hàm (hàm tự đọc `current_db_ctx`).
- `ExcelHttpBackend`: bọc `ClientSession` (streamable-http); `list_tools_openai` lấy từ
  `list_tools()`, `call_tool` qua session.
`BaseAgent` giữ `self.backends` thay cho `self.sessions`; `_call_tool` route theo
backend sở hữu tool.

### 3.3 Connection injection per-request
Mỗi lượt chat, **trước** khi vào graph:
```python
adapter = pool.adapter_for(project_id)            # mở/tái dùng pool theo project
sess    = pool.session_adapter_for(file_path)     # nếu có file upload
token = current_db_ctx.set(DbContext(primary=adapter, session=sess, allowed_tables=...))
try:
    result = await orchestrator.process_query(...)
finally:
    current_db_ctx.reset(token)
```

## 4. Thay đổi theo file

### 4.1 mcp-client (`mcp_agent`)

| File | Hành động |
|------|-----------|
| `servers/database/adapters/*` (base, factory, postgres, sqlite) | **Giữ nguyên logic**, di chuyển vào `mcp_agent/db/adapters/` (thành thư viện in-process). |
| `servers/database/database.py` | **Bỏ phần FastMCP/`mcp.run`**. Tách 21 thân tool thành `mcp_agent/tools/db_tools.py`, mỗi hàm đọc adapter từ `current_db_ctx` thay vì global. Bỏ `connect_db/connect_sqlite/...` khỏi tool LLM thấy (chuyển thành API control, §4.2). |
| `servers/chart-server/chart_server.py` | Tương tự: bỏ FastMCP, tách hàm `generate_*_chart` sang `mcp_agent/tools/chart_tools.py`, đọc engine từ ContextVar thay `_engine` global. |
| `servers/excel-server/excel_server.py` | **Đổi transport sang `streamable-http`** + `FastMCP(..., stateless_http=True, json_response=True)` + `mcp.run(transport="streamable-http", host, port)`. Giữ là server riêng. |
| `mcp_agent/tools/context.py` (mới) | `DbContext` + `current_db_ctx` ContextVar. |
| `mcp_agent/tools/registry.py` (mới) | Map tên tool → (callable, JSON schema); build danh sách OpenAI function cho db/chart. Thay phần `get_all_tools_for_openai` đối với db/chart. |
| `mcp_agent/tools/backend.py` (mới) | `ToolBackend` protocol, `InProcessBackend`, `ExcelHttpBackend`. |
| `mcp_agent/agents/base_agent.py` | Bỏ `connect_to_server` (stdio spawn + dò `.venv`). Thay `self.sessions`/`self._cached_tools` bằng `self.backends`. `get_all_tools_for_openai` gộp từ backends. Vòng lặp tool dispatch gọi `backend.call_tool`. |
| `mcp_agent/agents/{database,chart}_agent.py` | Gắn `InProcessBackend`. ExcelAgent gắn `ExcelHttpBackend(url=ENV)`. |
| `mcp_agent/servers.py` | Bỏ entry `database`/`chart` trong `SERVER_SCRIPTS`. Giữ (hoặc thay bằng URL env) cho excel. |
| `mcp_agent/orchestration/orchestrator.py` | Bỏ `connect_to_project_db`, `connect_session_file_db`, `connect_chart_to_project_db`, `disconnect_*`, `execute_sql` (loop qua sessions). Thay bằng quản lý pool + set ContextVar per-request. Orchestrator thành singleton. |
| `mcp_agent/graph/*` (mutation/readonly/create_table/workflow) | `_call_tool` đổi sang `agent.call_tool(...)` (route backend). Logic node giữ nguyên. |

### 4.2 api-server

| File | Hành động |
|------|-----------|
| `internal/features/chat/repository.py` | **Bỏ** cache per-user, `_detach_evictable`, `_inflight`, LRU/TTL, spawn subprocess, `server_script`. Xây **1 orchestrator** lúc app startup (lifespan). Thêm `ConnectionPool` (key `project_id` → adapter) sống ở đây. URL excel-server lấy từ env. |
| `internal/features/chat/service.py` | `_push_db_to_agents`/`connect_*` (gọi MCP tool) → thay bằng: resolve `db_url` (đã có qua `project_repo`) → `pool.adapter_for(project_id)` → set `current_db_ctx` quanh `process_query`. `set_connection_engine` (dialect) giữ logic, set vào ContextVar/agent. |
| Endpoint "Connect Database" (side panel) | Đổi từ gọi MCP `connect_db` → handler control: validate + lưu `projects.db_url` (mã hoá nếu PG ngoài) + probe `SELECT 1` qua pool in-process. Không expose cho LLM. |
| `docker-compose.yml` | **Bỏ** không cần spawn (vốn là subprocess, không phải service). **Thêm** service `excel-server` (image chạy `excel_server.py` HTTP, mở port, mount shared volume `.xlsx`). api-server nhận `EXCEL_MCP_URL`. |
| `.env` / config | Thêm `EXCEL_MCP_URL`, đường dẫn shared storage cho file. |

## 5. Phần XOÁ được (thu gọn đáng kể)

- Toàn bộ cơ chế spawn + dò `.venv` trong `base_agent.connect_to_server`.
- Per-user orchestrator cache + LRU eviction + refcount (`repository.py`).
- Các method `connect_*`/`disconnect_*`/`execute_sql` loop-qua-sessions trong orchestrator.
- FastMCP wrapper trong `database.py` và `chart_server.py` (giữ lại phần logic adapter/chart).
- Module-global `_primary_adapter`/`_session_adapter`/`_engine` (thay bằng ContextVar).

## 6. Excel qua HTTP — cụ thể

- Server: `FastMCP("excel", stateless_http=True, json_response=True)`,
  `mcp.run(transport="streamable-http", host="0.0.0.0", port=8931)`.
- Client (ExcelHttpBackend):
  ```python
  from mcp.client.streamable_http import streamablehttp_client
  async with streamablehttp_client(EXCEL_MCP_URL) as (r, w, _):
      async with ClientSession(r, w) as session:
          await session.initialize()
          await session.call_tool(name, args)
  ```
- **File .xlsx**: excel-mcp-server thao tác file trên đĩa của *nó*. api-server nhận
  upload → file phải tới được excel-server. Cách đơn giản: **shared volume** giữa
  api-server và excel-server (single host / docker-compose). Đa host → NFS/EFS hoặc
  thêm endpoint upload cho excel-server. (Xem §7.)

## 7. Vấn đề CÒN LẠI — không phải do bỏ MCP mà do storage

Bỏ MCP cho db/chart xoá được *cross-process file access*, nhưng **không** xoá bài toán
file-local nếu sau này **scale nhiều replica api-server**:

- **SQLite project DB** vẫn là file local → nhiều replica api-server cần **shared
  volume** (an toàn khi mỗi project chỉ 1 writer tại một thời điểm — mở rộng user-lock
  thành **project-lock**). NFS + nhiều writer = nguy cơ corruption.
- Muốn stateless/đa-replica thật sự → **Postgres-per-project** (mỗi project = 1
  database/schema). Không còn file, chỉ còn DSN. Đây là migration lớn hơn, làm sau.
- **Excel .xlsx** cùng tính chất file-local → shared volume hoặc 1 replica.

Quyết định cần chốt: **1 replica + shared volume (giữ SQLite)** hay **đa replica +
Postgres-per-project**. Plan này không phụ thuộc lựa chọn đó, nhưng §4.2 storage sẽ
khác theo hướng chọn.

## 8. Lộ trình đề xuất (giảm rủi ro, rollback dễ)

1. **Tách adapter thành thư viện** (`mcp_agent/db/adapters`) — thuần di chuyển, chưa
   đổi hành vi.
2. **ContextVar + InProcessBackend cho database**: chuyển `database.py` → `db_tools.py`,
   wire vào DatabaseAgent. Chạy song song đường MCP cũ qua feature-flag để so sánh.
3. **Chuyển orchestrator sang singleton + pool per-project**, set ContextVar per-request
   trong `service.py`. Bỏ push-db_url-qua-MCP.
4. **Chart** y hệt bước 2–3.
5. **Excel sang HTTP**: đổi transport, thêm compose service, đổi ExcelAgent sang
   ExcelHttpBackend, cấu hình shared volume.
6. **Dọn dẹp**: xoá spawn/LRU/connect_*-MCP/FastMCP wrapper (§5).
7. **(Tùy chọn) Postgres-per-project** nếu cần scale ngang nhiều replica api-server.

## 9. Cần verify trước khi code

- API đọc HTTP header / chạy stateless trong FastMCP (mcp ≥ 1.22) cho excel-server.
- Các tool hiện có nguy cơ nhả DSN ra result cần redact: `get_connection_info`, và
  error path của `connect_db`/`connect_sqlite`.
- `mcp_agent/graph/langgraph_checkpointer.py`: in-memory hay Postgres — ảnh hưởng việc
  resume "Execute" có sống qua restart/đa-replica không (độc lập với refactor này).
- Chỗ ghi file thực tế: `api-server/internal/databases/` và `temp_dbs/` → quyết shared
  storage cho excel-server và (nếu giữ SQLite) cho project DB.

## 10. Breakdown nhỏ (đơn vị sửa độc lập)

Mỗi mục là một commit/PR tự đứng được (compile + test xanh mới qua bước sau).

**P1 — Tách thư viện (no behavior change)**
- P1.1 Move `servers/database/adapters/*` → `mcp_agent/db/adapters/`, fix import.

**P2 — Scaffolding tool in-process (additive, chưa wire)**
- P2.1 `tools/context.py`: DbContext + `current_db_ctx`.
- P2.2 `tools/registry.py`: `@tool` + `openai_tools()` + auto-schema từ type hint.
- P2.3 `tools/db_tools.py`: port 21 tool, đọc ContextVar.
- P2.4 `tools/chart_tools.py`: port chart tool, đọc ContextVar.
- P2.5 `tools/backend.py`: ToolBackend + InProcessBackend.
- P2.6 Unit test parity db_tools trên temp SQLite.

**P3 — Wire backend vào agent (sau flag)**
- P3.1 BaseAgent: `self.backends` + `call_tool` routing (giữ MCP path).
- P3.2 graph `_call_tool` → `agent.call_tool`.
- P3.3 Bật InProcessBackend DB sau `USE_INPROCESS_DB`.

**P4 — Pool + ContextVar ở api-server**
- P4.1 `ConnectionPool[project_id]`.
- P4.2 `service.py`: set `current_db_ctx` per-request từ pool.
- P4.3 Endpoint Connect DB: probe `SELECT 1` qua pool, bỏ MCP `connect_db`.
- P4.4 Redact DSN ở `get_connection_info` + error path.

**P5 — Orchestrator singleton**
- P5.1 1 orchestrator lúc startup; bỏ cache/LRU `repository.py`.
- P5.2 Bỏ spawn/venv + `connect_*`/`execute_sql` orchestrator.

**P6 — Chart parity**
- P6.1 Bật InProcessBackend chart; bỏ chart-server spawn.

**P7 — Excel HTTP**
- P7.1 `excel_server.py` → streamable-http + stateless.
- P7.2 ExcelHttpBackend + ExcelAgent dùng `EXCEL_MCP_URL`.
- P7.3 compose service excel-server + shared volume *(chặn bởi quyết định §7)*.

**P8 — Dọn dẹp**
- P8.1 Bỏ flag, xoá FastMCP wrapper + global chết + entry servers.py.
- P8.2 Bọc sync adapter call trong `asyncio.to_thread`.
- P8.3 E2E test đa project + cập nhật docs.

**Thứ tự phụ thuộc:** P1 → P2 → P3 → P4 → P5 (DB chạy in-process hoàn chỉnh) → P6 (chart) → P7 (excel) → P8 (dọn). P7.3 chờ quyết định storage §7; các phase khác không bị chặn.
