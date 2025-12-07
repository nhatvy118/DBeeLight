# Hướng Dẫn Setup Database Server

## 1. Cài Đặt PostgreSQL

### macOS (với Homebrew):
```bash
brew install postgresql@15
brew services start postgresql@15
```

### Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

### Windows:
Tải và cài đặt từ: https://www.postgresql.org/download/windows/

## 2. Tạo Database

```bash
# Kết nối PostgreSQL
psql postgres

# Tạo database mới
CREATE DATABASE myapp_db;

# Tạo user (optional)
CREATE USER myuser WITH PASSWORD 'mypassword';
GRANT ALL PRIVILEGES ON DATABASE myapp_db TO myuser;

# Thoát
\q
```

## 3. Cài Đặt Dependencies

**Lưu ý:** Không cần tạo file `.env` nữa! Bạn sẽ cung cấp thông tin database trực tiếp qua chatbot.

```bash
cd database
uv sync
```

## 4. Sử Dụng với Client

```bash
cd ../mcp-client
uv run client.py ../database/database.py
```

**Lưu ý quan trọng:**
- ❌ **KHÔNG CẦN** activate venv thủ công (`source .venv/bin/activate`)
- ✅ Client tự động sử dụng Python từ `.venv` của database server
- ✅ Chỉ cần chạy `uv run client.py` là đủ
- ✅ Khi chạy, bạn sẽ thấy message: `Using Python from venv: .../database/.venv/bin/python`

## 5. Ví Dụ Workflow

### Bước 1: Kết nối Database
Đầu tiên, bạn cần kết nối database qua chatbot:

```
Query: Connect to database: host=localhost, port=5432, database=myapp_db, username=postgres, password=your_password
```

Hoặc:
```
Query: Kết nối database với host localhost, database myapp_db, user postgres, password your_password
```

### Bước 2: Thao tác với Database

1. **Tạo bảng:**
   - "Create a table called users with columns: id SERIAL, name VARCHAR(100), email VARCHAR(255) UNIQUE, age INTEGER, primary key id"

2. **Thêm dữ liệu:**
   - "Insert into users: name='Alice', email='alice@example.com', age=25"
   - "Add a user: name='Bob', email='bob@example.com', age=30"

3. **Truy vấn:**
   - "Show me all users"
   - "Get users where age > 25"
   - "Select name and email from users"

4. **Cập nhật:**
   - "Update users set age=26 where name='Alice'"
   - "Change email to 'alice.new@example.com' for user with id=1"

5. **Xóa:**
   - "Delete from users where id=1"
   - "Remove all users where age < 18"

6. **Quản lý:**
   - "List all tables"
   - "Describe the users table"

