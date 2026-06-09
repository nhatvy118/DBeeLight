# Design — Kiến trúc agent & tool execution

Tài liệu này mô tả thiết kế đích cho cách hệ thống thực thi tool của agent: **tool tự
viết (database, chart) chạy in-process; tool bên thứ ba (excel) chạy như MCP server
HTTP riêng.** Kế hoạch refactor chi tiết theo từng bước nằm ở
[`inprocess-tools-refactor-plan.md`](./inprocess-tools-refactor-plan.md).

---

## 1. Bối cảnh & vấn đề

Hệ thống là một ứng dụng LLM cho phép người dùng hỏi đáp/thao tác trên database của họ.
Một user có **nhiều project**, mỗi project có **một database riêng** (`projects.db_url`
— file SQLite nội bộ, hoặc DSN Postgres do user tự kết nối). Chat session gắn với cặp
`(user, project)`.

Kiến trúc hiện tại đặt mỗi nhóm tool (database/excel/chart) thành **một MCP server chạy
bằng stdio subprocess**, và orchestrator (nằm trong api-server) **spawn một bộ subprocess
riêng cho mỗi user**. Cách này gây ba vấn đề:

1. **Tốn RAM theo số user.** Mỗi user giữ ~3 subprocess (~190MB), phải có cache LRU +
   eviction để khỏi tràn bộ nhớ. Số user đồng thời bị chặn cứng bởi RAM.
2. **State danh tính nằm trong global của subprocess.** Connection DB được giữ ở biến
   module-global (`_primary_adapter`, `_session_adapter`, chart `_engine`). Vì mỗi user
   một process nên phải **ghi đè global mỗi lượt chat** để trỏ tới project đang active.
3. **Race condition tiềm ẩn.** Cùng một user mở 2 project (2 tab) chia sẻ một subprocess
   với một biến global → lượt này có thể chạy SQL trên DB của project kia. Hiện chỉ "an
   toàn" nhờ user-lock tuần tự hoá, không phải cô lập thật.

Quan sát cốt lõi: **gần như toàn bộ chi phí và rủi ro trên đến từ ranh giới process mà
MCP áp vào.** Mà database/chart là **code của chính dự án**, chỉ phục vụ **một consumer
duy nhất là orchestrator**. MCP chỉ thật sự đáng giá cho tool **bên thứ ba**, cần **cô
lập/sandbox**, hoặc cần **tái dùng cho client khác** — không cái nào áp dụng cho
database/chart.

---

## 2. Quyết định thiết kế

| Thành phần | Cách đóng gói | Lý do |
|---|---|---|
| **database, chart** | **Thư viện in-process** — gọi hàm Python trực tiếp từ orchestrator | Code của bạn, cần connection per-request, một consumer. MCP chỉ thêm IPC + ship credential + spawn. |
| **excel** | **MCP server riêng, transport HTTP** | Wrapper quanh `haris-musa/excel-mcp-server` (bên thứ ba). MCP là điểm tích hợp sạch: không fork code họ, chỉ nói protocol. |
| **orchestrator** | **Singleton** trong api-server | Bỏ cache per-user, bỏ LRU eviction, bỏ spawn. |
| **connection DB của user** | **Pool trong api-server**, key theo `project_id` | Cùng process với orchestrator + credential → khỏi token/header/shared-store cho phần này. |

Nguyên tắc nền: **chọn MCP hay in-process không thay đổi việc LLM thấy gì** (cả hai đều
nộp cùng mảng `tools`, cả hai đều giấu được URL). Nó chỉ thay đổi **cái giá để chạy
tool**: IPC + ship-credential + spawn (MCP) so với một lời gọi hàm (in-process). Với tool
tự viết, cái giá đó là thuần lỗ.

---

## 3. Kiến trúc đích

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
   Project data DB ─► SQLite files (shared volume)  HOẶC  Postgres-per-project (xem §8)
```

### Control plane vs data plane

- **api-server = control plane + orchestration.** Quyết định *nối DB nào*: nhận credential
  từ form, check ownership, lưu `projects.db_url`, mở/giữ connection pool, chạy LLM
  tool-loop. Orchestrator nằm ở đây dưới dạng library.
- **db_tools/chart_tools = data plane in-process.** Thực thi SQL/sinh chart, đọc adapter
  từ ngữ cảnh request.
- **excel-server = data plane out-of-process.** Service HTTP độc lập, thao tác file `.xlsx`.

---

## 4. Cơ chế then chốt

### 4.1 ContextVar thay module-global

Connection của request hiện tại được giữ trong `contextvars.ContextVar` — **task-local**
theo từng async request, thay vì global chia sẻ:

```python
@dataclass
class DbContext:
    primary: DatabaseAdapter | None = None      # DB của project
    session: DatabaseAdapter | None = None      # SQLite của file upload trong session
    allowed_tables: set[str] | None = None

current_db_ctx: ContextVar[DbContext] = ContextVar("current_db_ctx")
```

Vì ContextVar tách theo task, **hai request đồng thời cho hai project không đụng nhau** —
xoá tận gốc race condition của mô hình global cũ. Hỗ trợ đa project/đa user trở thành
chuyện tầm thường: chỉ là `pool.adapter_for(project_id)` rồi `set()` vào ContextVar.

### 4.2 Tool backend trừu tượng

Một interface chung để LangGraph workflow không cần biết tool chạy in-process hay HTTP:

```python
class ToolBackend(Protocol):
    def list_tools_openai(self) -> list[dict]: ...
    async def call_tool(self, name: str, args: dict) -> ToolResult: ...
```

- `InProcessBackend` — registry tên→hàm cho db_tools/chart_tools; `call_tool` dispatch
  thẳng hàm (hàm tự đọc `current_db_ctx`).
- `ExcelHttpBackend` — bọc MCP `ClientSession` qua streamable-http.

Nhờ vậy logic node trong workflow **gần như không đổi**; chỉ helper `_call_tool` đổi sang
`agent.call_tool(...)` (route theo backend sở hữu tool).

### 4.3 Connection injection per-request

Mỗi lượt chat, api-server resolve `(user, project)` → adapter từ pool, set vào ContextVar
**trước** khi vào graph, reset sau khi xong:

```python
adapter = pool.adapter_for(project_id)
sess    = pool.session_adapter_for(file_path)        # nếu có file upload
token = current_db_ctx.set(DbContext(primary=adapter, session=sess, allowed_tables=...))
try:
    result = await orchestrator.process_query(...)
finally:
    current_db_ctx.reset(token)
```

---

## 5. LLM thấy gì — và không thấy gì

LLM nằm trong tool-loop của orchestrator. Nó chỉ thấy: **system prompt + mảng `tools`
+ nội dung tool result**. Nó chỉ sinh ra: `{tên_tool, arguments}` (JSON).

**LLM "thấy hết tool" qua mảng `tools`** truyền vào `chat.completions.create(...)` — y
như trước, chỉ khác nguồn build: registry hàm Python thay cho MCP `list_tools()`. Model
không phân biệt tool là MCP hay in-process.

**Visibility (schema) tách rời execution (tiêm connection).** Schema đưa cho LLM **không
chứa** tham số connection; lúc chạy mới ghép adapter từ ContextVar:

| Tham số | Trong schema LLM thấy? | Nguồn lúc chạy |
|---|---|---|
| `query`, `table_name`, `where_clause`… | ✅ Có | LLM sinh ra |
| `adapter` / connection | ❌ Không | ContextVar (api-server tiêm) |

Vì `adapter` không nằm trong `properties` của schema, LLM không biết nó tồn tại, không
sinh được, không đọc được. Đây là cách cho LLM thấy *đầy đủ* tool mà vẫn giấu DB.

### Vị trí credential & ranh giới tin cậy

Có hai ranh giới tin cậy khác nhau:

- **LLM** — không tin cậy với secret → **không bao giờ** thấy DSN.
- **api-server (và excel-server)** — hạ tầng tin cậy → **được** thấy DSN, vì chúng cần để
  mở kết nối.

Với database/chart, credential **không bao giờ rời process api-server** (adapter là object
Python). Với excel (HTTP), nếu cần ngữ cảnh nhạy cảm thì truyền qua **header** (kênh
server-to-server), không qua context LLM.

Ba chỗ phải khoá để LLM không bao giờ đọc được URL:
1. Không để DSN/connection vào tool **arguments**.
2. Không để tool **result** trả DSN (vd `get_connection_info` phải redact host/password).
3. Không để **error message** nhả nguyên DSN.

---

## 6. Mô hình dữ liệu liên quan

```
users (google_sub)
  └─1:N─ projects (id, name, user_id, db_url)      ← mỗi project một DB riêng
            └─ session (user_id, project_id)        ← chat session thuộc (user, project)
```

- **App metadata** (users/projects/sessions/chat history) → Postgres của api-server
  (`_db_pool`), **giữ nguyên**, không liên quan refactor.
- **Project data DB** → file SQLite hoặc DSN Postgres ngoài, là thứ LLM query qua tool.

---

## 7. So sánh in-process vs MCP (vì sao hybrid)

| Tiêu chí | MCP-server | In-process |
|---|---|---|
| LLM thấy tool | qua `list_tools()` | qua registry — **giống hệt** |
| Nơi thực thi | process riêng | cùng process orchestrator |
| Connection/state | phải ship qua boundary (global/token/header) | object Python qua ContextVar |
| Overhead/call | serialize + IPC/HTTP | gọi hàm trực tiếp |
| Multi-tenant | spawn per-user hoặc token-keyed phức tạp | ContextVar task-local, không spawn |
| Cô lập lỗi/sandbox | ✅ có | ❌ không (chung runtime) |
| Interop/tái dùng | ✅ chuẩn protocol | ❌ khoá vào Python app |
| Debug | cross-process, 2 venv | 1 stack trace |

→ **database/chart**: in-process (code mình, cần ngữ cảnh per-request, một consumer).
→ **excel**: MCP/HTTP (bên thứ ba, đáng giá cô lập + protocol chuẩn).

---

## 8. Vấn đề mở: storage

Bỏ MCP cho db/chart xoá *cross-process file access*, nhưng **không** xoá bài toán
file-local nếu scale **nhiều replica api-server**:

- **SQLite project DB** là file local → đa replica cần **shared volume** (an toàn khi mỗi
  project chỉ 1 writer tại một thời điểm — mở rộng user-lock thành project-lock). NFS +
  nhiều writer = nguy cơ corruption.
- **Excel .xlsx** cùng tính chất → shared volume hoặc 1 replica.
- Muốn stateless/đa-replica thật sự → **Postgres-per-project** (mỗi project = 1
  database/schema), không còn file, chỉ còn DSN. Migration lớn hơn, làm sau.

**Quyết định cần chốt:** *1 replica + shared volume (giữ SQLite)* hay *đa replica +
Postgres-per-project*. Thiết kế này không phụ thuộc lựa chọn đó, nhưng phần storage của
api-server/compose sẽ khác theo hướng chọn.

---

## 9. Hệ quả

**Được:**
- Bỏ spawn-per-user, bỏ LRU/eviction → RAM không còn tăng theo số user.
- Hết race condition (ContextVar task-local).
- Đa project/đa user thành `pool.adapter_for(project_id)`.
- Bỏ IPC/serialize cho mọi tool DB/chart; debug 1 stack trace.
- Credential database/chart không rời process api-server.

**Phải xử lý khi triển khai:**
- **Blocking call**: adapter SQLite/psycopg đồng bộ phải chạy trong threadpool
  (`asyncio.to_thread`) để không nghẽn event loop.
- **Redact DSN** ở `get_connection_info` và error path.
- **Excel statelessness** vẫn vướng file-local → cần shared storage (§8).
- **Cô lập lỗi** kém hơn MCP: bug trong db_tools có thể ảnh hưởng api-server.

---

## 10. Tham chiếu

- Kế hoạch refactor từng bước (P1.1 → P8.3): [`inprocess-tools-refactor-plan.md`](./inprocess-tools-refactor-plan.md)
