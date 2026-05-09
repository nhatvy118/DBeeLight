# Multi-Agent Architecture

Tài liệu mô tả cách hoạt động và cách triển khai kiến trúc **multi-agent** trong project: luồng từ API → Orchestrator → Agent → MCP tools, và cách thêm agent mới.

---

## 1. Tổng quan

Hệ thống dùng **một Orchestrator** cho mỗi user. Orchestrator nắm **nhiều Agent** (hiện có DatabaseAgent; có thể thêm ExcelAgent, v.v.). Mỗi agent kết nối tới **MCP server** tương ứng và có **system prompt** riêng. Khi user gửi tin nhắn, Orchestrator **chọn agent** phù hợp (router) rồi **ủy quyền** xử lý cho agent đó.

```
User message
    → API (chat_usecase)
    → AgentRepository.get_agent(user_key)
    → MultiAgentOrchestrator.process_query(message)
    → Router chọn agent (database | excel | ...)
    → Agent.process_query(message)
    → LLM + tools (MCP) → response
    → Trả về user
```

---

## 2. Các thành phần chính

### 2.1. SessionManager (`mcp-client/mcp_agent/session.py`)

- **Vai trò:** Lưu và tải **lịch sử chat** (messages) theo user.
- **Lưu trữ:** Postgres (bảng `session`) khi user đã đăng nhập; in-memory khi anonymous.
- **API chính:** `create_session`, `load_session`, `list_sessions`, `get_current_messages`, `add_message`, `get_session_info`.
- **Lưu ý:** Một SessionManager được **dùng chung** cho toàn bộ Orchestrator và các agent trong orchestrator đó → một luồng hội thoại thống nhất.

### 2.2. BaseAgent (`mcp-client/mcp_agent/base_agent.py`)

- **Vai trò:** Lớp trừu tượng cho mọi agent: kết nối MCP, cache tools, vòng lặp chat + tool calls.
- **Trách nhiệm:**
  - Kết nối tới một hoặc nhiều MCP server qua `connect_to_server(server_name, script_path)`.
  - Gom toàn bộ tools từ các server → `get_all_tools_for_openai()`.
  - `process_query(query)`: load history từ SessionManager, gửi messages + tools lên OpenAI, xử lý tool_calls (gọi MCP), lặp đến khi model trả về response thuần text (không gọi tool nữa).
- **Subclass bắt buộc:** Implement `_build_system_prompt()` (system prompt riêng cho từng loại agent).

### 2.3. DatabaseAgent (`mcp-client/mcp_agent/database_agent.py`)

- **Vai trò:** Agent chuyên **database**: kết nối DB, schema, CRUD, SQL.
- **Kế thừa:** `BaseAgent`.
- **Khác biệt:** Chỉ định nghĩa **system prompt** hướng dẫn khi nào dùng tool nào (connect_db, list_tables, create_table, execute_query, …).
- **MCP server:** `database/database.py` (PostgreSQL + SQLite).

### 2.4. MultiAgentOrchestrator (`mcp-client/mcp_agent/orchestrator.py`)

- **Vai trò:** Nắm danh sách agent và **routing** mỗi tin nhắn tới đúng agent.
- **Luồng:**
  1. Nhận `process_query(query)`.
  2. Nếu có **một** agent → gửi luôn cho agent đó.
  3. Nếu có **nhiều** agent → gọi LLM router (system prompt + user message) → nhận `agent_id` (ví dụ `"database"` hoặc `"excel"`) → gọi `agent.process_query(query)`.
- **Session:** Dùng chung một `SessionManager` với tất cả agent → lịch sử hội thoại thống nhất.
- **API giống agent:** `process_query`, `sessions` (proxy từ agent đầu tiên), `session_manager`, `cleanup()` để API/health check không cần biết bên trong là orchestrator hay agent đơn.

### 2.5. AgentRepository (`api-server/internal/repositories/agent_repository.py`)

- **Vai trò:** Tạo và cache **một Orchestrator cho mỗi user**.
- **Luồng:**
  1. `get_agent(user_key)` → nếu đã có orchestrator cho user thì trả về.
  2. Chưa có: tạo `SessionManager(db_pool, user_id)`, tạo **một hoặc nhiều** agent (hiện tại: một `DatabaseAgent`), connect agent tới các MCP server (`database/database.py`, `excel-server/excel_server.py`), tạo `MultiAgentOrchestrator(agents=[...], session_manager=...)`, lưu vào `_orchestrators[user_key]`.
  3. Trả về orchestrator.
- **Cấu hình:** `_default_servers` (đường dẫn script MCP), `_model` (OpenAI model).

---

## 3. Luồng xử lý một tin nhắn chat

1. **Frontend** gửi `POST /api/chat` với `message`, `session_id` (optional), `project_id` (optional).
2. **ChatUseCase.chat:**  
   - Gọi `agent_repo.get_agent(user_key)` → nhận **Orchestrator**.  
   - Load hoặc tạo session (theo `session_id` / `project_id`).  
   - Gọi `agent.process_query(query)` (trên orchestrator).  
   - Trả về `(response_text, session_id)`.
3. **Orchestrator.process_query:**  
   - `_route(query)` → chọn `agent_id`.  
   - Gọi `agent.process_query(query)` trên agent được chọn.
4. **Agent (ví dụ DatabaseAgent).process_query:**  
   - Load history từ `session_manager.get_current_messages()`.  
   - Build messages (chỉ user + assistant text khi load từ history; không gửi tool/tool_calls cũ lên API).  
   - Thêm user message mới.  
   - Vòng lặp: gọi OpenAI với tools → nếu có tool_calls thì gọi MCP (theo server có tool đó) → thêm tool result vào messages → lặp đến khi không còn tool_calls.  
   - Lưu message vào SessionManager, trả về text cuối cùng.
5. **API** trả response + `session_id` cho frontend.

---

## 4. Cách thêm agent mới (implementation)

### Bước 1: Tạo class agent kế thừa BaseAgent

Tạo file ví dụ `mcp-client/mcp_agent/excel_agent.py`:

```python
from typing import Optional
from mcp_agent.base_agent import BaseAgent
from mcp_agent.session import SessionManager

class ExcelAgent(BaseAgent):
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        session_manager: Optional[SessionManager] = None,
        agent_id: str = "excel",
    ):
        if session_manager is None:
            raise ValueError("session_manager is required for ExcelAgent")
        super().__init__(agent_id=agent_id, model=model, session_manager=session_manager)

    def _build_system_prompt(self) -> str:
        return """You are an Excel agent. Use the available tools to work with spreadsheets..."""
```

- **agent_id:** Chuỗi duy nhất (ví dụ `"excel"`) để router trả về.
- **system prompt:** Viết rõ khi nào dùng tool nào và luôn có bước “trả lời cuối bằng text, không gọi thêm tool”.

### Bước 2: Kết nối agent với MCP server

Trong **AgentRepository.get_agent()** (api-server):

- Tạo thêm agent (ví dụ `ExcelAgent`) với **cùng** `session_manager` đã tạo cho user.
- Chỉ connect agent đó tới MCP server tương ứng (ví dụ chỉ `excel-server/excel_server.py`), không cần connect DatabaseAgent tới excel.
- Đưa agent vào list: `agents = [db_agent, excel_agent]`.
- Tạo orchestrator: `MultiAgentOrchestrator(agents=agents, session_manager=session_manager, router_model=self._model)`.

Ví dụ cấu trúc:

```python
session_manager = SessionManager(db_pool=self._db_pool, user_id=user_key)
db_agent = DatabaseAgent(model=self._model, session_manager=session_manager, agent_id="database")
excel_agent = ExcelAgent(model=self._model, session_manager=session_manager, agent_id="excel")

await db_agent.connect_to_server("database", str(base_path / "database/database.py"))
await excel_agent.connect_to_server("excel", str(base_path / "excel-server/excel_server.py"))

orchestrator = MultiAgentOrchestrator(agents=[db_agent, excel_agent], session_manager=session_manager, router_model=self._model)
```

### Bước 3: Export agent mới (optional)

Trong `mcp-client/mcp_agent/__init__.py` thêm:

```python
from mcp_agent.excel_agent import ExcelAgent
__all__ = [..., "ExcelAgent"]
```

Router sẽ tự dùng `agent_id` ("database", "excel") từ system prompt; không cần đăng ký thêm.

---

## 5. Lưu ý kỹ thuật

- **History gửi lên OpenAI:** Chỉ gồm message **user** và **assistant** (chỉ phần text, không gửi message có `tool_calls` hay `tool` từ history) để tránh lỗi 400 (tool_call_id không khớp).
- **Giới hạn vòng lặp:** `max_iterations` trong BaseAgent (ví dụ 25) để tránh lặp vô hạn; system prompt cần nhấn mạnh “sau khi xong việc phải trả lời bằng text, không gọi thêm tool”.
- **Một agent, nhiều tool:** Một agent (ví dụ DatabaseAgent) có thể kết nối **nhiều** MCP server và dùng **tất cả** tools từ các server đó; multi-agent là **nhiều agent** (nhiều “bộ não”), mỗi agent có thể có nhiều tool.

---

## 6. Cây thư mục liên quan

```
mcp-server/
├── docs/
│   └── README.md                 # (file này)
├── mcp-client/
│   └── mcp_agent/
│       ├── __init__.py           # Export BaseAgent, DatabaseAgent, MultiAgentOrchestrator, SessionManager
│       ├── base_agent.py         # BaseAgent: MCP + tools + process_query loop
│       ├── database_agent.py     # DatabaseAgent: system prompt database
│       ├── orchestrator.py       # MultiAgentOrchestrator: router + delegate
│       └── session.py            # SessionManager: lưu/tải lịch sử chat
├── api-server/
│   └── internal/
│       ├── repositories/
│       │   └── agent_repository.py   # Tạo Orchestrator + agents cho từng user
│       └── usecases/
│           └── chat_usecase.py       # Gọi get_agent → process_query
├── database/
│   ├── database.py              # MCP server: tools PostgreSQL + SQLite
│   └── adapters/                # Database adapters (Factory Pattern)
│       ├── __init__.py
│       ├── base.py              # DatabaseAdapter (abstract base class)
│       ├── postgres.py          # PostgresAdapter
│       ├── sqlite.py            # SQLiteAdapter
│       └── factory.py           # DatabaseAdapterFactory
└── excel-server/
    └── excel_server.py           # Stdio adapter cho excel-mcp-server (haris-musa)
```

---

## 7. Database Adapters (Factory Pattern)

MCP server `database/database.py` sử dụng **Factory Pattern** để hỗ trợ nhiều loại database (PostgreSQL, SQLite) mà không cần conditional logic lặp lại trong từng tool.

### 7.1. Kiến trúc

```
database/
├── database.py              # MCP server - các tools (connect_db, list_tables, ...)
└── adapters/
    ├── __init__.py          # Export adapters
    ├── base.py              # DatabaseAdapter (ABC)
    ├── postgres.py          # PostgresAdapter (asyncpg)
    ├── sqlite.py            # SQLiteAdapter (aiosqlite)
    └── factory.py           # DatabaseAdapterFactory
```

### 7.2. DatabaseAdapter (Abstract Base Class)

File: `database/adapters/base.py`

Interface chung cho mọi database adapter:

```python
from abc import ABC, abstractmethod

class DatabaseAdapter(ABC):
    @abstractmethod
    async def connect(self, **kwargs) -> str: ...
    
    @abstractmethod
    async def disconnect(self) -> str: ...
    
    @abstractmethod
    async def list_tables(self) -> str: ...
    
    @abstractmethod
    async def describe_table(self, table_name: str) -> str: ...
    
    @abstractmethod
    async def create_table(self, table_name: str, columns: str, primary_key: str = None) -> str: ...
    
    @abstractmethod
    async def insert_data(self, table_name: str, data: dict) -> str: ...
    
    @abstractmethod
    async def select_data(self, table_name: str, columns: str = "*", ...) -> str: ...
    
    @abstractmethod
    async def execute_query(self, query: str) -> str: ...
    
    # ... các method khác
```

### 7.3. Concrete Adapters

**PostgresAdapter** (`database/adapters/postgres.py`):
- Sử dụng `asyncpg` để kết nối PostgreSQL
- Connection pooling (`asyncpg.Pool`)
- Hỗ trợ đầy đủ: schema info, constraints, triggers, size statistics

**SQLiteAdapter** (`database/adapters/sqlite.py`):
- Sử dụng `aiosqlite` để kết nối file `.db`
- Tự tạo file nếu chưa tồn tại
- Một số hạn chế của SQLite:
  - Không hỗ trợ `ALTER COLUMN` (modify type)
  - Không hỗ trợ thêm/xóa constraint sau khi tạo bảng
  - Không có size statistics chi tiết như PostgreSQL

### 7.4. DatabaseAdapterFactory

File: `database/adapters/factory.py`

Factory tạo adapter phù hợp từ connection string:

```python
from database.adapters import DatabaseAdapterFactory

# SQLite
adapter = DatabaseAdapterFactory.create("sqlite:///path/to/db.sqlite")
adapter = DatabaseAdapterFactory.create("/path/to/project.db")  # auto-detect by extension

# PostgreSQL
adapter = DatabaseAdapterFactory.create("postgres://user:pass@host:5432/dbname")

# Direct creation
pg_adapter = DatabaseAdapterFactory.create_postgres()
sqlite_adapter = DatabaseAdapterFactory.create_sqlite()

# Detect type without creating
db_type = DatabaseAdapterFactory.detect_type("sqlite:///my.db")  # returns "sqlite"
```

### 7.5. Cách MCP server sử dụng adapters

File `database/database.py` giờ đơn giản:

```python
from database.adapters import DatabaseAdapter, DatabaseAdapterFactory

_adapter: Optional[DatabaseAdapter] = None

@mcp.tool()
async def connect_sqlite(file_path: str) -> str:
    global _adapter
    _adapter = DatabaseAdapterFactory.create_sqlite()
    return await _adapter.connect(file_path=file_path)

@mcp.tool()
async def connect_db(host: str, port: int, database: str, username: str, password: str) -> str:
    global _adapter
    _adapter = DatabaseAdapterFactory.create_postgres()
    return await _adapter.connect(host=host, port=port, database=database, username=username, password=password)

@mcp.tool()
async def list_tables() -> str:
    return await _adapter.list_tables()  # Hoạt động giống nhau cho cả SQLite và PostgreSQL

# ... tương tự cho các tool khác
```

### 7.6. Thêm database adapter mới

Để hỗ trợ thêm một loại database (ví dụ MySQL):

1. **Tạo adapter class:**

```python
# database/adapters/mysql.py
from database.adapters.base import DatabaseAdapter

class MySQLAdapter(DatabaseAdapter):
    async def connect(self, host: str, port: int, ...) -> str:
        # Implementation sử dụng aiomysql
        ...
    
    async def list_tables(self) -> str:
        # MySQL-specific query
        ...
    
    # Implement tất cả abstract methods
```

2. **Cập nhật factory:**

```python
# database/adapters/factory.py
from database.adapters.mysql import MySQLAdapter

class DatabaseAdapterFactory:
    @staticmethod
    def create(connection_string: str) -> DatabaseAdapter:
        if conn_str.startswith("mysql://"):
            return MySQLAdapter()
        # ... existing logic
```

3. **Export:**

```python
# database/adapters/__init__.py
from database.adapters.mysql import MySQLAdapter
__all__ = [..., "MySQLAdapter"]
```

4. **Thêm tool trong MCP server (optional):**

```python
# database/database.py
@mcp.tool()
async def connect_mysql(host: str, port: int, database: str, username: str, password: str) -> str:
    global _adapter
    _adapter = DatabaseAdapterFactory.create(f"mysql://{username}:{password}@{host}:{port}/{database}")
    return await _adapter.connect(...)
```

---

## 8. Tóm tắt

**Multi-agent** = một Orchestrator + nhiều Agent (Database, Excel, …), mỗi agent có system prompt và MCP tools riêng; Orchestrator **router** theo nội dung tin nhắn rồi **ủy quyền** cho đúng agent.

**Factory Pattern cho Database** = một interface `DatabaseAdapter` + các concrete adapters (PostgreSQL, SQLite) + factory để tạo adapter từ connection string. MCP tools delegate sang adapter, không cần biết đang dùng database nào.
