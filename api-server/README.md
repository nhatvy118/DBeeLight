# API Server

FastAPI server để kết nối Frontend với MCP Agent.

## Cài đặt

```bash
cd api-server
uv sync
```

## Chạy Server

```bash
uv run api-server
```

Hoặc:

```bash
uv run python -m api_server
```

Server sẽ chạy tại `http://localhost:5001`

## API Endpoints

### POST `/api/chat`
Gửi message và nhận response từ agent.

**Request:**
```json
{
  "message": "Kết nối database localhost:5432, database: testdb, user: postgres, password: mypass",
  "session_id": "optional_session_id"
}
```

**Response:**
```json
{
  "success": true,
  "response": "Response từ agent...",
  "session_id": "session_id"
}
```

### GET `/api/sessions`
Lấy danh sách tất cả sessions.

**Response:**
```json
{
  "success": true,
  "sessions": [
    {
      "session_id": "...",
      "session_name": "...",
      "created_at": "...",
      "message_count": 10
    }
  ]
}
```

### POST `/api/sessions/new`
Tạo session mới.

**Request:**
```json
{
  "name": "Optional session name"
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "...",
  "session_info": {...}
}
```

### GET `/api/sessions/<session_id>`
Lấy thông tin và messages của một session.

**Response:**
```json
{
  "success": true,
  "session_info": {...},
  "messages": [...]
}
```

### GET `/api/health`
Health check endpoint.

