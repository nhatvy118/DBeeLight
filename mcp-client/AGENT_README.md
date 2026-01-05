# Database Agent AI

Agent AI thông minh để phân tích query của user và tự động chọn tool phù hợp từ MCP servers.

## Tính năng

- 🤖 **Agent AI thông minh**: System prompt chi tiết về khi nào dùng tool nào
- 🔧 **Tool Routing**: Tự động phân tích query và chọn tool phù hợp nhất
- 🔌 **Multi-Server Support**: Hỗ trợ kết nối nhiều MCP servers cùng lúc
- 📝 **Verbose Mode**: Hiển thị chi tiết tool calls để debug
- ✅ **Error Handling**: Xử lý lỗi tốt hơn với thông báo rõ ràng
- 💾 **Session Management**: Lưu lịch sử chat theo session, có thể tiếp tục cuộc hội thoại sau khi tắt app

## Cài đặt

```bash
cd mcp-client
uv sync
```

Đảm bảo có file `.env` với `OPENAI_API_KEY`:

```env
OPENAI_API_KEY=your_api_key_here
```

## Sử dụng

### Kết nối một server (Database)

```bash
uv run agent.py ../database/database.py
```

### Kết nối nhiều servers

```bash
uv run agent.py ../database/database.py ../excel-summary/excel_summary.py
```

## System Prompt

Agent có system prompt chi tiết về:

1. **Kết nối Database**: Khi nào dùng `connect_db`, `get_connection_info`, `disconnect_database`
2. **Quản lý Schema**: Khi nào dùng `list_tables`, `describe_table`, `get_schema`
3. **Tạo Tables**: Khi nào dùng `create_table`, `create_db_from_spec`
4. **CRUD Operations**: Khi nào dùng `select_data`, `insert_data`, `update_data`, `delete_data`
5. **SQL Queries**: Khi nào dùng `execute_query`, `validate_sql`, `explain_sql`
6. **Documentation**: Khi nào dùng `generate_schema_doc`

## Ví dụ Queries

### Kết nối Database
```
💬 Query: Kết nối database localhost:5432, database: testdb, user: postgres, password: mypass
```

### Xem Schema
```
💬 Query: Có những table nào trong database?
💬 Query: Cấu trúc table users
💬 Query: Xem toàn bộ schema
```

### SELECT Data
```
💬 Query: Hiển thị tất cả users
💬 Query: Lấy users có age > 25, sắp xếp theo name
💬 Query: Xem 10 products đầu tiên
```

### INSERT Data
```
💬 Query: Thêm user mới: name='Alice', email='alice@example.com', age=30
```

### UPDATE Data
```
💬 Query: Cập nhật email của user có id=1 thành 'newemail@example.com'
```

### DELETE Data
```
💬 Query: Xóa user có id=5
```

### SQL Queries
```
💬 Query: SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id
💬 Query: Giải thích execution plan của query SELECT * FROM users WHERE age > 25
```

## Workflow của Agent

1. **Phân tích Query**: Agent đọc và hiểu ý định của user
2. **Chọn Tool**: Dựa vào system prompt, agent chọn tool phù hợp nhất
3. **Thực thi**: Gọi tool với parameters đúng
4. **Xử lý Kết quả**: Trả về kết quả cho user hoặc tiếp tục với tool khác nếu cần

## Session Management

Agent tự động lưu lịch sử chat vào thư mục `sessions/`. Mỗi session là một file JSON chứa toàn bộ cuộc hội thoại.

### Tạo Session Mới

Khi khởi động, agent sẽ tự động tạo session mới hoặc hỏi bạn có muốn load session cũ không.

### Quản lý Sessions

Trong chat loop, bạn có thể dùng các lệnh sau:

- **`new`**: Tạo session mới
  ```
  💬 Query: new
  Session name (optional): My Database Session
  ✅ New session created: abc12345
  ```

- **`sessions`**: Liệt kê tất cả sessions
  ```
  💬 Query: sessions
  📚 Found 3 session(s):
    1. My Database Session (abc12345)
       Created: 2024-01-15T10:30:00
       Messages: 15 ← current
    2. Test Session (def67890)
       Created: 2024-01-14T09:20:00
       Messages: 8
  ```

- **`load <session_id>`**: Load một session cũ
  ```
  💬 Query: load abc12345
  ✅ Loaded session: abc12345
     Session: My Database Session
     Messages: 15
  ```

### Lợi ích của Session

- ✅ **Nhớ context**: Agent nhớ những gì đã làm trước đó
- ✅ **Chat liên tiếp**: Có thể tiếp tục cuộc hội thoại sau khi tắt app
- ✅ **Nhiều sessions**: Quản lý nhiều cuộc hội thoại khác nhau
- ✅ **Lịch sử đầy đủ**: Lưu cả user queries, tool calls, và responses

### Format Session File

Mỗi session file có format:
```json
{
  "session_id": "abc12345",
  "created_at": "2024-01-15T10:30:00",
  "session_name": "My Database Session",
  "messages": [
    {
      "role": "user",
      "content": "Kết nối database...",
      "timestamp": "2024-01-15T10:30:15"
    },
    {
      "role": "assistant",
      "content": "",
      "tool_calls": [...],
      "timestamp": "2024-01-15T10:30:16"
    }
  ]
}
```

## Verbose Mode

Trong chat loop, gõ `verbose` để bật/tắt verbose mode:

```
💬 Query: verbose
Verbose mode: ON
```

Verbose mode sẽ hiển thị:
- Tool nào đang được gọi
- Arguments được truyền vào
- Kết quả trả về
- Lỗi nếu có

## So sánh với client.py

| Tính năng | client.py | agent.py |
|-----------|-----------|----------|
| System Prompt | ❌ | ✅ Chi tiết |
| Tool Routing | ⚠️ Cơ bản | ✅ Thông minh |
| Multi-Server | ❌ | ✅ |
| Verbose Mode | ❌ | ✅ |
| Error Handling | ⚠️ Cơ bản | ✅ Tốt hơn |
| Examples | ❌ | ✅ Có trong prompt |
| Session Management | ❌ | ✅ Lưu lịch sử |

## Tùy chỉnh

### Đổi Model

Trong `agent.py`, thay đổi:

```python
agent = DatabaseAgent(model="gpt-4o")  # Thay vì gpt-4o-mini
```

### Thêm System Prompt

Chỉnh sửa method `_build_system_prompt()` trong class `DatabaseAgent` để thêm hướng dẫn mới.

## Troubleshooting

### Lỗi "No MCP servers connected"
- Đảm bảo đã truyền đường dẫn server script khi chạy
- Kiểm tra đường dẫn có đúng không

### Lỗi "Tool not found"
- Kiểm tra server đã được kết nối chưa
- Kiểm tra tool name có đúng không (case-sensitive)

### Agent chọn sai tool
- Bật verbose mode để xem agent đang nghĩ gì
- Cải thiện system prompt trong `_build_system_prompt()`
- Thử dùng model tốt hơn (gpt-4o thay vì gpt-4o-mini)

