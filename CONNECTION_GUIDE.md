# Hướng Dẫn Kết Nối Frontend với Backend

## Cấu Trúc

- **Frontend**: React app trong `frontend/`
- **Backend**: Flask API server trong `api-server/`
- **MCP Agent**: Agent AI trong `mcp-client/`

## Cài Đặt

### 1. Backend (API Server)

```bash
cd api-server
uv sync
```

Đảm bảo có file `.env` với `OPENAI_API_KEY`:
```env
OPENAI_API_KEY=your_api_key_here
```

### 2. Frontend

```bash
cd frontend
npm install
```

## Chạy Ứng Dụng

### Bước 1: Chạy Backend

```bash
cd api-server
uv run api-server
```

Backend sẽ chạy tại `http://localhost:5001` (port 5001 để tránh conflict với AirPlay trên macOS)

### Bước 2: Chạy Frontend

**Trong terminal khác** (quan trọng: phải chạy riêng):

```bash
cd frontend
npm run dev
```

Frontend sẽ chạy tại `http://localhost:5173`

**Lưu ý**: Bạn cần mở browser tại `http://localhost:5173` (KHÔNG phải 5001!)

## Kiểm Tra Kết Nối

1. **Mở browser tại `http://localhost:5173`** (đây là frontend UI)
2. Backend API chạy tại `http://localhost:5001` (không cần mở trực tiếp)
3. Nhập một message và gửi
4. Kiểm tra console (F12) để xem có lỗi không

## Troubleshooting

### Lỗi CORS
- Đảm bảo `flask-cors` đã được cài đặt trong `api-server`
- Kiểm tra backend đang chạy tại port 5000

### Lỗi kết nối API
- Kiểm tra backend đã start chưa (port 5001)
- Kiểm tra `VITE_API_URL` trong `.env` (nếu có)
- Vite proxy sẽ tự động forward `/api/*` đến `http://localhost:5001`

### Lỗi MCP Server
- Đảm bảo các MCP servers (`database/`, `excel-summary/`) đã được cài đặt
- Kiểm tra đường dẫn trong `api-server/app.py` (DEFAULT_SERVERS)

## API Endpoints

- `POST /api/chat` - Gửi message
- `GET /api/sessions` - Lấy danh sách sessions
- `POST /api/sessions/new` - Tạo session mới
- `GET /api/sessions/<id>` - Lấy thông tin session
- `GET /api/health` - Health check

