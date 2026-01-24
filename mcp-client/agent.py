import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Optional, Dict, List, Any
from contextlib import AsyncExitStack
from datetime import datetime
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env


class SessionManager:
    """Quản lý lịch sử chat theo session"""
    
    def __init__(self, sessions_dir: str = "sessions"):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(exist_ok=True)
        self.current_session_id: Optional[str] = None
        self.current_session_file: Optional[Path] = None
    
    def create_session(self, session_name: Optional[str] = None, project_id: Optional[str] = None) -> str:
        """Tạo session mới"""
        session_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if session_name:
            filename = f"{timestamp}_{session_name}_{session_id}.json"
        else:
            filename = f"{timestamp}_session_{session_id}.json"
        
        self.current_session_id = session_id
        self.current_session_file = self.sessions_dir / filename
        
        # Tạo file session với metadata
        session_data = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "session_name": session_name or f"Session {session_id}",
            "project_id": project_id,
            "messages": []
        }
        
        self._save_session(session_data)
        return session_id
    
    def load_session(self, session_id: str) -> bool:
        """Load session từ file"""
        # Tìm file session
        session_files = list(self.sessions_dir.glob(f"*_{session_id}.json"))
        if not session_files:
            return False
        
        self.current_session_file = session_files[0]
        self.current_session_id = session_id
        return True
    
    def list_sessions(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Liệt kê tất cả sessions, có thể lọc theo project_id"""
        sessions = []
        for session_file in sorted(self.sessions_dir.glob("*.json"), reverse=True):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    session_project_id = data.get("project_id")
                    
                    # Nếu có project_id filter, chỉ lấy sessions thuộc project đó
                    if project_id is not None and session_project_id != project_id:
                        continue
                    
                    sessions.append({
                        "session_id": data.get("session_id", ""),
                        "session_name": data.get("session_name", ""),
                        "created_at": data.get("created_at", ""),
                        "message_count": len(data.get("messages", [])),
                        "project_id": session_project_id,
                        "file": session_file.name
                    })
            except Exception:
                continue
        return sessions
    
    def get_current_messages(self) -> List[Dict[str, Any]]:
        """Lấy messages của session hiện tại"""
        if not self.current_session_file or not self.current_session_file.exists():
            return []
        
        try:
            with open(self.current_session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("messages", [])
        except Exception:
            return []
    
    def add_message(self, role: str, content: str, tool_calls: Optional[List] = None):
        """Thêm message vào session"""
        if not self.current_session_file:
            return
        
        try:
            with open(self.current_session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {
                "session_id": self.current_session_id,
                "created_at": datetime.now().isoformat(),
                "messages": []
            }
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        if tool_calls:
            message["tool_calls"] = tool_calls
        
        data["messages"].append(message)
        data["updated_at"] = datetime.now().isoformat()
        
        self._save_session(data)
    
    def _save_session(self, data: Dict[str, Any]):
        """Lưu session data vào file"""
        if not self.current_session_file:
            return
        
        try:
            with open(self.current_session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️  Warning: Failed to save session: {e}")
    
    def get_session_info(self) -> Dict[str, Any]:
        """Lấy thông tin session hiện tại"""
        if not self.current_session_file or not self.current_session_file.exists():
            return {}
        
        try:
            with open(self.current_session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    "session_id": data.get("session_id", ""),
                    "session_name": data.get("session_name", ""),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "project_id": data.get("project_id")
                }
        except Exception:
            return {}


class DatabaseAgent:
    """
    Agent AI thông minh để phân tích query và quyết định khi nào dùng tool nào.
    Agent này có system prompt chi tiết về từng tool và best practices.
    """
    
    def __init__(self, model: str = "gpt-4o-mini", session_manager: Optional[SessionManager] = None):
        # MCP sessions - hỗ trợ nhiều servers
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        
        # OpenAI client
        self.openai = OpenAI()
        self.model = model
        
        # Cache tools từ mỗi server
        self._cached_tools: Dict[str, List] = {}
        
        # System prompt với hướng dẫn chi tiết về tools
        self.system_prompt = self._build_system_prompt()
        
        # Session manager để lưu lịch sử
        self.session_manager = session_manager or SessionManager()
    
    def _build_system_prompt(self) -> str:
        """Xây dựng system prompt chi tiết về khi nào dùng tool nào"""
        return """Bạn là một Database Agent AI chuyên nghiệp, giúp người dùng thao tác với PostgreSQL database thông qua các tools có sẵn.

## QUY TẮC QUAN TRỌNG:

### 1. KẾT NỐI DATABASE (BẮT BUỘC ĐẦU TIÊN)
- **connect_db**: PHẢI gọi tool này TRƯỚC khi dùng bất kỳ tool nào khác
  - Khi user yêu cầu làm việc với database nhưng chưa kết nối
  - Khi user cung cấp thông tin database (host, port, database name, username, password)
  - Ví dụ: "Kết nối database localhost:5432, database: mydb, user: postgres, password: 123"
  
- **get_connection_info**: Kiểm tra trạng thái kết nối hiện tại
  - Khi user hỏi "đã kết nối chưa?" hoặc "database nào đang dùng?"
  
- **disconnect_database**: Ngắt kết nối
  - Khi user yêu cầu ngắt kết nối hoặc chuyển database khác

### 2. QUẢN LÝ SCHEMA (CẤU TRÚC DATABASE)

- **list_tables**: Liệt kê tất cả tables
  - Khi user hỏi "có những table nào?", "show tables", "list all tables"
  - Nên gọi TRƯỚC khi làm việc với table cụ thể để biết table nào tồn tại
  
- **describe_table**: Xem cấu trúc của một table
  - Khi user hỏi về cấu trúc table, columns, data types
  - Ví dụ: "cấu trúc table users", "columns của table products"
  - Nên gọi TRƯỚC khi SELECT/INSERT/UPDATE để biết đúng column names và types
  
- **get_schema**: Xem toàn bộ schema của database
  - Khi user hỏi "schema của database", "cấu trúc toàn bộ database"
  - Hữu ích khi cần hiểu tổng quan về database
  
- **get_table_stats**: Thống kê về table (số rows, size)
  - Khi user hỏi "có bao nhiêu records?", "kích thước table", "statistics"

### 3. TẠO VÀ QUẢN LÝ TABLES

- **create_table**: Tạo table mới
  - Khi user yêu cầu "tạo table", "create table", "tạo bảng"
  - Cần columns definition và optional primary key
  - Ví dụ: "Tạo table users với id SERIAL, name VARCHAR(100), email VARCHAR(255)"
  
- **alter_table**: Sửa đổi cấu trúc table (thêm, xóa, sửa, đổi tên cột)
  - **add_column**: Thêm cột mới vào table
    - Khi user yêu cầu "thêm cột", "add column", "thêm column"
    - Cần column_name và column_def (ví dụ: "VARCHAR(255)", "INTEGER NOT NULL")
    - Ví dụ: "Thêm cột email VARCHAR(255) vào table users"
  
  - **drop_column**: Xóa cột khỏi table
    - Khi user yêu cầu "xóa cột", "drop column", "remove column"
    - Cần column_name
    - Ví dụ: "Xóa cột old_column từ table users"
  
  - **modify_column**: Sửa đổi cột (đổi type, thêm/xóa NOT NULL, set default, etc.)
    - Khi user yêu cầu "sửa cột", "modify column", "alter column", "thay đổi type"
    - Cần column_name và column_def
    - Ví dụ: "Sửa cột name thành VARCHAR(200)", "Thêm NOT NULL cho cột email"
  
  - **rename_column**: Đổi tên cột
    - Khi user yêu cầu "đổi tên cột", "rename column"
    - Cần column_name và new_column_name
    - Ví dụ: "Đổi tên cột old_name thành new_name trong table users"
  
- **create_db_from_spec**: Tạo schema từ SQL DDL
  - Khi user cung cấp SQL DDL statements hoàn chỉnh
  - Hữu ích khi tạo nhiều tables cùng lúc
  
- **manage_constraint**: Thêm/xóa constraints (CHECK, FOREIGN KEY, etc.)
  - Khi user yêu cầu thêm constraint hoặc xóa constraint
  
- **manage_trigger**: Tạo/xóa triggers
  - Khi user yêu cầu quản lý triggers

### 4. THAO TÁC DỮ LIỆU (CRUD)

- **select_data**: SELECT data từ table
  - Khi user hỏi "hiển thị", "lấy", "select", "tìm", "xem data"
  - Hỗ trợ WHERE, ORDER BY, LIMIT
  - Ví dụ: "Lấy tất cả users có age > 18", "Hiển thị 10 products đầu tiên"
  - Nên dùng tool này thay vì execute_query cho SELECT đơn giản
  
- **preview_table**: Xem preview của table (mặc định 10 rows)
  - Khi user muốn "xem nhanh", "preview", "xem mẫu data"
  - Hữu ích để hiểu data structure trước khi query phức tạp
  
- **insert_data**: INSERT data vào table
  - Khi user yêu cầu "thêm", "insert", "tạo record mới"
  - Cần dictionary với column names và values
  - Ví dụ: "Thêm user mới: name='John', email='john@example.com'"
  
- **update_data**: UPDATE data trong table
  - Khi user yêu cầu "cập nhật", "update", "sửa", "thay đổi"
  - Cần WHERE clause để xác định rows cần update
  - Ví dụ: "Cập nhật email của user có id=1 thành 'new@example.com'"
  
- **delete_data**: DELETE data từ table
  - Khi user yêu cầu "xóa", "delete", "remove"
  - Cần WHERE clause để xác định rows cần xóa
  - CẨN THẬN: Xóa data là thao tác nguy hiểm!

### 5. SQL QUERIES

- **execute_query**: Thực thi SQL query tùy ý
  - Khi user cung cấp SQL query trực tiếp
  - Khi query phức tạp (JOIN, subquery, aggregation, etc.)
  - Ví dụ: "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
  - Nên dùng cho queries phức tạp mà các tools đơn giản không đủ
  
- **run_mutation**: Chạy mutation query (INSERT/UPDATE/DELETE)
  - Tương tự execute_query nhưng chỉ cho mutations
  - Có validation để đảm bảo an toàn
  
- **validate_sql**: Validate SQL syntax (không execute)
  - Khi user muốn kiểm tra SQL trước khi chạy
  - Hữu ích để debug SQL errors
  
- **explain_sql**: Xem execution plan của query
  - Khi user hỏi về performance, "tại sao query chậm?"
  - Hữu ích để optimize queries

### 6. DOCUMENTATION

- **generate_schema_doc**: Tạo documentation cho schema
  - Khi user yêu cầu "tạo tài liệu", "documentation", "export schema doc"
  - Hỗ trợ format text hoặc markdown

### 7. DATABASE MANAGEMENT

- **list_databases**: Liệt kê tất cả databases trên server
  - Khi user hỏi "có những database nào?"

## WORKFLOW TỐI ƯU:

1. **Khi user hỏi về database:**
   - Kiểm tra connection (get_connection_info) → Nếu chưa kết nối, yêu cầu connect_db
   - Nếu cần làm việc với table: list_tables → describe_table (nếu cần) → thực hiện thao tác

2. **Khi user yêu cầu SELECT:**
   - Nếu query đơn giản: dùng select_data
   - Nếu query phức tạp (JOIN, subquery): dùng execute_query
   - Nếu chỉ muốn xem nhanh: dùng preview_table

3. **Khi user yêu cầu INSERT/UPDATE/DELETE:**
   - Nếu đơn giản: dùng insert_data/update_data/delete_data
   - Nếu phức tạp: dùng execute_query hoặc run_mutation

4. **Khi user cung cấp SQL trực tiếp:**
   - Validate trước (validate_sql) nếu cần
   - Execute (execute_query hoặc run_mutation)

5. **Luôn kiểm tra schema trước khi thao tác:**
   - describe_table để biết đúng column names và types
   - Tránh lỗi do sai tên column hoặc type mismatch

## LƯU Ý QUAN TRỌNG:

- LUÔN kiểm tra connection trước khi dùng tools khác
- LUÔN kiểm tra table tồn tại (list_tables) trước khi thao tác
- LUÔN kiểm tra schema (describe_table) trước khi INSERT/UPDATE để đảm bảo đúng columns
- CẨN THẬN với DELETE - luôn yêu cầu xác nhận hoặc WHERE clause rõ ràng
- Ưu tiên dùng tools chuyên biệt (select_data, insert_data) thay vì execute_query khi có thể
- Khi có lỗi, đọc kỹ error message và sửa lại query/tool call

## VÍ DỤ QUERIES:

User: "Kết nối database localhost:5432, database: testdb, user: postgres, password: mypass"
→ connect_db(host="localhost", port=5432, database="testdb", username="postgres", password="mypass")

User: "Có những table nào?"
→ list_tables()

User: "Cấu trúc table users"
→ describe_table(table_name="users")

User: "Hiển thị tất cả users"
→ select_data(table_name="users")

User: "Lấy users có age > 25, sắp xếp theo name"
→ select_data(table_name="users", where_clause="age > 25", order_by="name ASC")

User: "Thêm user mới: name='Alice', email='alice@example.com', age=30"
→ insert_data(table_name="users", data={"name": "Alice", "email": "alice@example.com", "age": 30})

User: "Cập nhật email của user có id=1 thành 'newemail@example.com'"
→ update_data(table_name="users", data={"email": "newemail@example.com"}, where_clause="id = 1")

User: "Thêm cột email VARCHAR(255) vào table users"
→ alter_table(action="add_column", table_name="users", column_name="email", column_def="VARCHAR(255)")

User: "Xóa cột old_column từ table users"
→ alter_table(action="drop_column", table_name="users", column_name="old_column")

User: "Sửa cột name thành VARCHAR(200) trong table users"
→ alter_table(action="modify_column", table_name="users", column_name="name", column_def="VARCHAR(200)")

User: "Đổi tên cột old_name thành new_name trong table users"
→ alter_table(action="rename_column", table_name="users", column_name="old_name", new_column_name="new_name")

User: "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
→ execute_query(query="SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id")

Hãy phân tích query của user và chọn tool phù hợp nhất!"""

    async def connect_to_server(self, server_name: str, server_script_path: str):
        """Kết nối đến một MCP server
        
        Args:
            server_name: Tên định danh cho server (ví dụ: "database", "excel")
            server_script_path: Đường dẫn đến server script
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        script_path = Path(server_script_path).resolve()
        script_dir = script_path.parent
        
        if is_python:
            venv_dirs = [".venv", "venv", "env"]
            python_executable = None
            
            for venv_dir in venv_dirs:
                venv_path = script_dir / venv_dir
                if venv_path.exists() and venv_path.is_dir():
                    if sys.platform == "win32":
                        python_exe = venv_path / "Scripts" / "python.exe"
                    else:
                        python_exe = venv_path / "bin" / "python"
                    
                    if python_exe.exists():
                        python_executable = str(python_exe)
                        break
            
            if python_executable:
                command = python_executable
                args = [str(script_path)]
                print(f"[{server_name}] Using Python from venv: {python_executable}")
            else:
                command = "python"
                args = [server_script_path]
                print(f"[{server_name}] Using system Python: {command}")
        else:
            command = "node"
            args = [server_script_path]
        
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=None,
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(stdio, write)
        )

        await session.initialize()
        self.sessions[server_name] = session

        # Cache tools
        response = await session.list_tools()
        self._cached_tools[server_name] = response.tools
        print(f"[{server_name}] Connected! Available tools: {len(response.tools)}")
        
        # In danh sách tools
        for tool in response.tools:
            print(f"  - {tool.name}: {tool.description[:80]}...")

    async def process_query(self, query: str, verbose: bool = False) -> str:
        """Xử lý query của user với agent AI thông minh
        
        Args:
            query: Query từ user
            verbose: In ra thông tin chi tiết về tool calls
        """
        if not self.sessions:
            raise RuntimeError("No MCP servers connected. Please connect to at least one server first.")

        # Thu thập tất cả tools từ tất cả servers
        all_tools = []
        for server_name, tools in self._cached_tools.items():
            for tool in tools:
                all_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })

        # Load lịch sử từ session (nếu có)
        history_messages = self.session_manager.get_current_messages()
        
        # Tạo messages với system prompt và lịch sử
        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            }
        ]
        
        # Thêm lịch sử (bỏ system messages cũ nếu có)
        for msg in history_messages:
            if msg.get("role") != "system":  # Bỏ system messages cũ
                # Chuyển đổi format từ session format sang OpenAI format
                message_dict = {
                    "role": msg["role"],
                    "content": msg["content"]
                }
                
                # Xử lý tool_calls nếu có
                if "tool_calls" in msg:
                    message_dict["tool_calls"] = msg["tool_calls"]
                
                # Xử lý tool messages (có tool_call_id)
                if msg["role"] == "tool":
                    try:
                        tool_data = json.loads(msg["content"])
                        message_dict["tool_call_id"] = tool_data.get("tool_call_id")
                        message_dict["name"] = tool_data.get("name")
                        message_dict["content"] = tool_data.get("content", msg["content"])
                    except (json.JSONDecodeError, TypeError):
                        # Nếu không parse được, giữ nguyên
                        pass
                
                messages.append(message_dict)
        
        # Thêm query mới
        messages.append({
            "role": "user",
            "content": query,
        })
        
        # Lưu user query vào session
        self.session_manager.add_message("user", query)

        final_text_chunks = []
        max_iterations = 10  # Giới hạn số lần lặp để tránh infinite loop
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            
            try:
                completion = self.openai.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools if all_tools else None,
                    tool_choice="auto",
                    temperature=0.1,  # Giảm randomness để chọn tool chính xác hơn
                )

                message = completion.choices[0].message
                content_text = message.content or ""
                if content_text:
                    final_text_chunks.append(content_text)

                tool_calls = message.tool_calls or []

                if not tool_calls:
                    # Không có tool calls nữa, đây là final response
                    # Lưu final assistant response vào session
                    if content_text:
                        self.session_manager.add_message("assistant", content_text)
                    break

                assistant_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(assistant_message)
                
                # Lưu assistant message với tool calls vào session
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
                self.session_manager.add_message(
                    "assistant", 
                    message.content or "", 
                    tool_calls=tool_calls_data
                )

                # Tìm server nào có tool này và gọi
                for tc in tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        tool_args = {}
                        if verbose:
                            print(f"⚠️  Warning: Failed to parse arguments for {tool_name}")

                    # Tìm server có tool này
                    target_server = None
                    for server_name, tools in self._cached_tools.items():
                        if any(t.name == tool_name for t in tools):
                            target_server = server_name
                            break

                    if target_server is None:
                        error_msg = f"Tool '{tool_name}' not found in any connected server"
                        if verbose:
                            print(f"❌ {error_msg}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": json.dumps({"error": error_msg}),
                        })
                        continue

                    if verbose:
                        print(f"🔧 [{target_server}] Calling {tool_name} with args: {tool_args}")

                    try:
                        result = await self.sessions[target_server].call_tool(tool_name, tool_args)
                        result_content = result.content

                        if not isinstance(result_content, str):
                            result_content = str(result_content)

                        if verbose:
                            print(f"✅ [{target_server}] {tool_name} returned: {result_content[:200]}...")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": json.dumps(result_content),
                        })
                        
                        # Lưu tool result vào session (format đặc biệt cho tool messages)
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": result_content
                        }
                        # Lưu dưới dạng JSON string để dễ parse lại
                        self.session_manager.add_message(
                            "tool",
                            json.dumps(tool_message)
                        )
                    except Exception as e:
                        error_msg = f"Error calling {tool_name}: {str(e)}"
                        if verbose:
                            print(f"❌ {error_msg}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": json.dumps({"error": error_msg}),
                        })

            except Exception as e:
                error_msg = f"Error in iteration {iteration}: {str(e)}"
                if verbose:
                    print(f"❌ {error_msg}")
                final_text_chunks.append(f"Error: {error_msg}")
                break

        if iteration >= max_iterations:
            final_text_chunks.append("\n⚠️  Reached maximum iterations. Please simplify your query.")

        final_response = "\n".join(chunk for chunk in final_text_chunks if chunk)
        
        # Lưu final response vào session (nếu có)
        if final_response and not tool_calls:
            # Nếu không có tool calls, có nghĩa là đã có final response
            # Response đã được lưu ở trên, chỉ cần update nếu cần
            pass
        
        return final_response

    async def chat_loop(self, verbose: bool = False):
        """Chạy interactive chat loop"""
        print("\n" + "="*60)
        print("🤖 Database Agent AI Started!")
        print("="*60)
        print(f"Connected servers: {', '.join(self.sessions.keys())}")
        
        # Hiển thị thông tin session
        session_info = self.session_manager.get_session_info()
        if session_info:
            print(f"📝 Session: {session_info.get('session_name', 'Unknown')} ({session_info.get('session_id', '')})")
            print(f"   Messages: {session_info.get('message_count', 0)}")
        else:
            # Tạo session mới nếu chưa có
            session_id = self.session_manager.create_session()
            print(f"📝 New session created: {session_id}")
        
        print("\nCommands:")
        print("  - Type your query to chat")
        print("  - 'quit' or 'exit' to exit")
        print("  - 'verbose' to toggle verbose mode")
        print("  - 'new' to start a new session")
        print("  - 'sessions' to list all sessions")
        print("  - 'load <session_id>' to load a session")
        print("="*60)

        while True:
            try:
                query = input("\n💬 Query: ").strip()

                if query.lower() in ["quit", "exit"]:
                    break
                
                if query.lower() == "verbose":
                    verbose = not verbose
                    print(f"Verbose mode: {'ON' if verbose else 'OFF'}")
                    continue
                
                if query.lower() == "new":
                    session_name = input("Session name (optional): ").strip() or None
                    session_id = self.session_manager.create_session(session_name)
                    print(f"✅ New session created: {session_id}")
                    session_info = self.session_manager.get_session_info()
                    if session_info:
                        print(f"   Session: {session_info.get('session_name', 'Unknown')}")
                    continue
                
                if query.lower() == "sessions":
                    sessions = self.session_manager.list_sessions()
                    if not sessions:
                        print("No sessions found.")
                    else:
                        print(f"\n📚 Found {len(sessions)} session(s):")
                        for i, sess in enumerate(sessions, 1):
                            current_marker = " ← current" if sess["session_id"] == self.session_manager.current_session_id else ""
                            print(f"  {i}. {sess['session_name']} ({sess['session_id']})")
                            print(f"     Created: {sess['created_at']}")
                            print(f"     Messages: {sess['message_count']}{current_marker}")
                    continue
                
                if query.lower().startswith("load "):
                    session_id = query[5:].strip()
                    if self.session_manager.load_session(session_id):
                        print(f"✅ Loaded session: {session_id}")
                        session_info = self.session_manager.get_session_info()
                        if session_info:
                            print(f"   Session: {session_info.get('session_name', 'Unknown')}")
                            print(f"   Messages: {session_info.get('message_count', 0)}")
                    else:
                        print(f"❌ Session not found: {session_id}")
                    continue

                if not query:
                    continue

                print("\n🤔 Processing...")
                response = await self.process_query(query, verbose=verbose)
                
                # Lưu final response vào session
                if response:
                    # Response đã được lưu trong process_query, chỉ cần hiển thị
                    pass
                
                print("\n" + "="*60)
                print("📋 Response:")
                print("="*60)
                print(response)
                print("="*60)

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {str(e)}")
                import traceback
                if verbose:
                    traceback.print_exc()

    async def cleanup(self):
        """Dọn dẹp resources"""
        await self.exit_stack.aclose()


async def main():
    """Main function với hỗ trợ nhiều servers"""
    if len(sys.argv) < 2:
        print("Usage: python agent.py <server1_script> [server2_script] ...")
        print("\nExample:")
        print("  python agent.py ../database/database.py")
        print("  python agent.py ../database/database.py ../excel-summary/excel_summary.py")
        sys.exit(1)

    # Tạo session manager và agent
    session_manager = SessionManager()
    
    # Kiểm tra xem có muốn load session cũ không
    sessions = session_manager.list_sessions()
    if sessions:
        print(f"\n📚 Found {len(sessions)} previous session(s).")
        print("Options:")
        print("  1. Start new session (default)")
        print("  2. Load existing session")
        choice = input("Your choice (1/2): ").strip()
        
        if choice == "2":
            print("\nAvailable sessions:")
            for i, sess in enumerate(sessions[:10], 1):  # Hiển thị tối đa 10 sessions
                print(f"  {i}. {sess['session_name']} ({sess['session_id']}) - {sess['message_count']} messages")
            
            session_input = input("\nEnter session number or ID: ").strip()
            
            # Nếu là số, lấy session theo index
            if session_input.isdigit():
                idx = int(session_input) - 1
                if 0 <= idx < len(sessions):
                    session_id = sessions[idx]["session_id"]
                    session_manager.load_session(session_id)
                    print(f"✅ Loading session: {sessions[idx]['session_name']}")
                else:
                    print("❌ Invalid session number. Starting new session.")
                    session_manager.create_session()
            else:
                # Nếu là ID
                if session_manager.load_session(session_input):
                    print(f"✅ Loading session: {session_input}")
                else:
                    print("❌ Session not found. Starting new session.")
                    session_manager.create_session()
        else:
            session_manager.create_session()
    else:
        session_manager.create_session()
    
    agent = DatabaseAgent(model="gpt-4o-mini", session_manager=session_manager)  # Có thể đổi sang gpt-4o
    
    try:
        # Kết nối đến tất cả servers
        for i, server_path in enumerate(sys.argv[1:], 1):
            server_name = Path(server_path).stem  # Lấy tên file không có extension
            await agent.connect_to_server(server_name, server_path)
        
        await agent.chat_loop(verbose=False)
    finally:
        await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

