# API Server

FastAPI server để kết nối Frontend với MCP Agent.

## Cài đặt

```bash
cd api-server
source .venv/bin/activate
uv sync
```

## Chạy Server

```bash
uv run api-server
```

Hoặc:

```bash
uv run python -m internal
```

Server sẽ chạy tại `http://localhost:5001`

## Google OAuth2 Login (Authorization Code)

Tạo file `api-server/.env`:

```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
FRONTEND_URL=http://localhost:5173
SESSION_SECRET=change-me
# Optional (comma-separated)
CORS_ORIGINS=http://localhost:5173
```

Redirect URI cần khai báo trong Google Console sẽ phụ thuộc bạn start login từ đâu:
- Nếu bạn login qua frontend proxy: `http://localhost:5173/api/auth/google/callback`
- Nếu bạn login trực tiếp vào backend: `http://localhost:5001/api/auth/google/callback`

Endpoints:
- `GET /api/auth/google/login?next=/chat`
- `GET /api/auth/google/callback`
- `GET /api/auth/me`
- `POST /api/auth/logout`

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

