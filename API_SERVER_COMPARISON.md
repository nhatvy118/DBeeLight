# So Sánh API Server: DatabaseAgent vs LangGraph

## Tổng Quan

API server có **2 phiên bản**:

1. **`api_server/__init__.py`** - Sử dụng `DatabaseAgent` (mặc định)
2. **`api_server/langraph_api.py`** - Sử dụng `LangGraphMCPAgent` (mới)

## So Sánh Chi Tiết

| Tính Năng | DatabaseAgent API | LangGraph API |
|-----------|-------------------|---------------|
| **Agent Type** | `DatabaseAgent` | `LangGraphMCPAgent` |
| **File** | `api_server/__init__.py` | `api_server/langraph_api.py` |
| **Command** | `uv run python -m api_server` | `uv run python -m api_server.langraph_api` |
| **Workflow** | Simple loop | Graph-based workflow |
| **State Management** | Manual (session-based) | Automatic (graph state) |
| **Session/Thread** | `session_id` | `thread_id` |
| **Conditional Routing** | ❌ | ✅ |
| **Checkpointing** | ❌ | ✅ |
| **Multi-step Tasks** | ⚠️ Basic | ✅ Advanced |

---

## Cách Chạy

### DatabaseAgent API (Mặc định)

```bash
cd api-server
uv sync
uv run python -m api_server
```

**Khi nào dùng:**
- ✅ Cần session management
- ✅ Workflow đơn giản
- ✅ Cần system prompt chi tiết

---

### LangGraph API

```bash
cd api-server
uv sync
uv run python -m api_server.langraph_api
```

**Khi nào dùng:**
- ✅ Workflow phức tạp
- ✅ Cần state management tốt
- ✅ Cần conditional routing
- ✅ Cần checkpointing

---

## API Endpoints

### DatabaseAgent API

```python
POST /api/chat
{
  "message": "...",
  "session_id": "optional"
}

GET /api/sessions
POST /api/sessions/new
GET /api/sessions/{session_id}
```

### LangGraph API

```python
POST /api/chat
{
  "message": "...",
  "thread_id": "optional"  # Thay vì session_id
}

GET /api/sessions  # Trả về note về thread_id
POST /api/sessions/new  # Tạo thread_id mới
GET /api/sessions/{session_id}  # Lấy thread info
```

**Lưu ý:** LangGraph sử dụng `thread_id` cho checkpointing, không có session management như DatabaseAgent.

---

## Ví Dụ Sử Dụng

### DatabaseAgent API

```bash
# Start server
uv run python -m api_server

# Frontend sẽ gửi:
POST /api/chat
{
  "message": "Kết nối database...",
  "session_id": "abc123"
}
```

### LangGraph API

```bash
# Start server
uv run python -m api_server.langraph_api

# Frontend sẽ gửi:
POST /api/chat
{
  "message": "Kết nối database...",
  "thread_id": "def456"  # Hoặc để null để dùng "default"
}
```

---

## Migration Guide

### Từ DatabaseAgent sang LangGraph

1. **Thay đổi command:**
   ```bash
   # Cũ
   uv run python -m api_server
   
   # Mới
   uv run python -m api_server.langraph_api
   ```

2. **Thay đổi API calls:**
   ```javascript
   // Cũ
   {
     "message": "...",
     "session_id": "abc123"
   }
   
   // Mới
   {
     "message": "...",
     "thread_id": "def456"  // hoặc bỏ qua để dùng "default"
   }
   ```

3. **Session management:**
   - DatabaseAgent: Có session management đầy đủ
   - LangGraph: Sử dụng thread_id cho checkpointing

---

## Kết Luận

- **DatabaseAgent API**: Phù hợp cho hầu hết use cases, có session management
- **LangGraph API**: Phù hợp cho workflows phức tạp, cần state management tốt

Cả hai đều tương thích với Frontend hiện tại, chỉ cần thay đổi cách gọi API nếu muốn dùng LangGraph.

