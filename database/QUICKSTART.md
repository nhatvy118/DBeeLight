# Quick Start Guide

## Cài Đặt Nhanh

### 1. Cài đặt dependencies cho database server:
```bash
cd database
uv sync
```

### 2. Cài đặt dependencies cho client:
```bash
cd ../mcp-client
uv sync
```

### 3. Chạy client:
```bash
uv run client.py ../database/database.py
```

## ❓ Câu Hỏi Thường Gặp

### Q: Tôi có cần activate venv không?
**A: KHÔNG!** Client tự động sử dụng Python từ `.venv` của database server. Bạn chỉ cần chạy `uv run client.py` là đủ.

### Q: Tôi thấy lỗi "no such file or directory: venv/bin/activate"
**A:** Database server sử dụng `.venv` (với dấu chấm), không phải `venv`. Nhưng bạn không cần activate thủ công vì client tự động xử lý.

### Q: Làm sao biết client đang dùng venv?
**A:** Khi chạy client, bạn sẽ thấy message:
```
Using Python from venv: /path/to/database/.venv/bin/python
Connected to server with tools: [...]
```

### Q: Tôi muốn chạy server trực tiếp (không qua client)?
**A:** Bạn có thể chạy:
```bash
cd database
uv run database.py
```
Nhưng server này được thiết kế để chạy qua MCP client, không phải standalone.

## Workflow Đơn Giản

1. **Cài đặt** (chỉ cần làm 1 lần):
   ```bash
   cd database && uv sync
   cd ../mcp-client && uv sync
   ```

2. **Chạy** (mỗi lần sử dụng):
   ```bash
   cd mcp-client
   uv run client.py ../database/database.py
   ```

3. **Kết nối database** (trong chatbot):
   ```
   Connect to database: host=localhost, port=5432, database=myapp_db, username=postgres, password=mypassword
   ```

4. **Sử dụng** các lệnh CRUD qua chatbot!

