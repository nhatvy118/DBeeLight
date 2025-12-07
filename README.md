# MCP Server Projects

Dự án này chứa các MCP (Model Context Protocol) servers và client để tương tác với chúng.

## Các Servers

### 1. Weather Server (`weather/`)
MCP server cung cấp thông tin thời tiết từ National Weather Service API.

**Sử dụng:**
```bash
cd mcp-client
uv run client.py ../weather/weather.py
```

### 2. Database Server (`database/`)
MCP server cung cấp các công cụ CRUD để thao tác với PostgreSQL database.

**Cài đặt:**
```bash
cd database
uv sync  # Tạo .venv và cài đặt dependencies
```

**Lưu ý:** Không cần file `.env` nữa! Bạn sẽ cung cấp thông tin database qua chatbot.

**Sử dụng:**
```bash
cd mcp-client
uv run client.py ../database/database.py
```

Client sẽ tự động sử dụng Python từ `.venv` của database server để đảm bảo tất cả dependencies đã được cài đặt.

## MCP Client (`mcp-client/`)

Client để kết nối và tương tác với các MCP servers sử dụng OpenAI GPT.

**Cài đặt:**
```bash
cd mcp-client
uv sync  # Tạo .venv và cài đặt dependencies
```

**Yêu cầu:**
- File `.env` với `OPENAI_API_KEY`

**Sử dụng:**
```bash
cd mcp-client
uv run client.py <path_to_server_script>
```

**Lưu ý về Virtual Environment:**
- Client tự động phát hiện và sử dụng Python từ `.venv` của server (nếu có)
- Điều này đảm bảo server chạy với đúng dependencies đã được cài đặt
- Nếu không tìm thấy venv, client sẽ fallback về system Python

Xem thêm chi tiết trong các README của từng server.