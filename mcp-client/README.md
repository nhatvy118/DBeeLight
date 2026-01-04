# MCP Client

Client để kết nối và tương tác với các MCP servers sử dụng OpenAI GPT.

## Cài Đặt

1. Cài đặt dependencies:
```bash
cd mcp-client
uv sync
```

2. Tạo file `.env` với OpenAI API key:
```bash
echo "OPENAI_API_KEY=your_api_key_here" > .env
```

## Yêu Cầu

- File `.env` với `OPENAI_API_KEY`
- Python 3.12+

## Sử Dụng

### Kết nối với Database Server:
```bash
cd mcp-client
uv run client.py ../database/database.py
```

### Kết nối với Excel & Summary Server:
```bash
cd mcp-client
uv run client.py ../excel-summary/excel_summary.py
```

### Cú pháp chung:
```bash
uv run client.py <path_to_server_script>
```

## Tính Năng

### Tự động phát hiện Virtual Environment
- Client tự động phát hiện và sử dụng Python từ `.venv` của server (nếu có)
- Điều này đảm bảo server chạy với đúng dependencies đã được cài đặt
- Nếu không tìm thấy venv, client sẽ fallback về system Python

### Interactive Chat Loop
- Sau khi kết nối server, bạn có thể chat với AI
- AI sẽ tự động phân tích query và gọi các tools phù hợp
- Gõ `quit` để thoát

### Tool Caching
- Tools được cache sau khi kết nối để tăng hiệu suất
- Không cần list tools lại mỗi query

## Ví Dụ

### Kết nối Database Server:
```bash
$ uv run client.py ../database/database.py
Using Python from venv: .../database/.venv/bin/python

Connected to server with tools: ['connect_db', 'get_connection_info', ...]

MCP Client Started!
Type your queries or 'quit' to exit.

Query: Connect to database: host=localhost, port=5432, database=testdb, username=postgres, password=mypassword
```

### Kết nối Excel & Summary Server:
```bash
$ uv run client.py ../excel-summary/excel_summary.py
Using Python from venv: .../excel-summary/.venv/bin/python

Connected to server with tools: ['import_excel', 'export_excel', ...]

MCP Client Started!
Type your queries or 'quit' to exit.

Query: Import data from ./data.xlsx
```

## Lưu Ý

- Client hỗ trợ cả Python (`.py`) và JavaScript (`.js`) servers
- Đảm bảo server đã được cài đặt dependencies trước khi kết nối
- Client sử dụng OpenAI GPT-4o-mini mặc định (có thể thay đổi trong code)

