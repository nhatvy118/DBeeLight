# MCP Database Server

MCP Server cung cấp các công cụ để thao tác với PostgreSQL database thông qua các query tự nhiên.

**Đặc điểm:** Bạn có thể cung cấp thông tin kết nối database (host, username, password) trực tiếp qua chatbot, không cần file cấu hình!

## Cài Đặt

1. Cài đặt dependencies:
```bash
cd database
uv sync
```

## Kết Nối Database

**Không cần file .env!** Bạn sẽ cung cấp thông tin database qua chatbot khi sử dụng.

## Các Tools Có Sẵn

### 0. `connect_database` ⭐ (BẮT BUỘC ĐẦU TIÊN)
Kết nối đến PostgreSQL database. **Phải gọi tool này trước khi sử dụng các tools khác.**

**Parameters:**
- `host`: Database host (e.g., "localhost" hoặc "127.0.0.1")
- `port`: Database port (mặc định PostgreSQL là 5432)
- `database`: Tên database
- `username`: Username để đăng nhập
- `password`: Password

**Ví dụ:**
- "Connect to database: host=localhost, port=5432, database=myapp_db, username=postgres, password=mypassword"
- "Kết nối database với host localhost, database testdb, user postgres, password 123456"

### 1. `get_connection_info`
Xem thông tin kết nối database hiện tại (không hiển thị password).

**Ví dụ:**
- "Show me current database connection info"
- "What database am I connected to?"

### 2. `disconnect_database`
Ngắt kết nối database hiện tại.

**Ví dụ:**
- "Disconnect from database"
- "Close database connection"

### 3. `create_table`

### 1. `create_table`
Tạo bảng mới trong database.

**Parameters:**
- `table_name`: Tên bảng
- `columns`: Định nghĩa các cột (SQL format)
- `primary_key`: (Optional) Tên cột làm primary key

**Ví dụ:**
- "Create a table called users with columns: id SERIAL, name VARCHAR(100), email VARCHAR(255)"
- "Create table products with id SERIAL, name VARCHAR(200), price DECIMAL(10,2), primary key id"

### 2. `insert_data`
Thêm dữ liệu vào bảng.

**Parameters:**
- `table_name`: Tên bảng
- `data`: Dictionary với key là tên cột, value là giá trị

**Ví dụ:**
- "Insert into users: name='John', email='john@example.com'"
- "Add a new product: name='Laptop', price=999.99"

### 3. `select_data`
Truy vấn dữ liệu từ bảng.

**Parameters:**
- `table_name`: Tên bảng
- `columns`: (Optional) Các cột cần lấy (default: "*")
- `where_clause`: (Optional) Điều kiện WHERE
- `limit`: (Optional) Giới hạn số dòng
- `order_by`: (Optional) Sắp xếp

**Ví dụ:**
- "Select all users"
- "Get users where age > 18"
- "Show me the first 10 products ordered by price"

### 4. `update_data`
Cập nhật dữ liệu trong bảng.

**Parameters:**
- `table_name`: Tên bảng
- `data`: Dictionary với các giá trị mới
- `where_clause`: Điều kiện WHERE để xác định dòng cần update

**Ví dụ:**
- "Update users set email='newemail@example.com' where id=1"
- "Change product price to 899.99 where name='Laptop'"

### 5. `delete_data`
Xóa dữ liệu từ bảng.

**Parameters:**
- `table_name`: Tên bảng
- `where_clause`: Điều kiện WHERE để xác định dòng cần xóa

**Ví dụ:**
- "Delete from users where id=1"
- "Remove all products where price < 10"

### 9. `execute_query`
Thực thi một SQL query tùy chỉnh.

**Parameters:**
- `query`: SQL query

**Ví dụ:**
- "Execute: SELECT COUNT(*) FROM users"
- "Run this query: SELECT * FROM products WHERE price BETWEEN 100 AND 500"

### 10. `list_tables`
Liệt kê tất cả các bảng trong database.

**Ví dụ:**
- "Show me all tables"
- "List tables in the database"

### 11. `describe_table`
Xem cấu trúc của một bảng (các cột, kiểu dữ liệu).

**Parameters:**
- `table_name`: Tên bảng

**Ví dụ:**
- "Describe the users table"
- "Show me the structure of products table"

## Sử Dụng

### Chạy Server (nếu muốn test riêng):
```bash
cd database
uv run database.py
```

### Sử dụng với Client (khuyến nghị):
```bash
cd ../mcp-client
uv run client.py ../database/database.py
```

**Lưu ý:**
- ❌ **KHÔNG CẦN** activate venv thủ công
- ✅ Client tự động phát hiện và sử dụng Python từ `.venv` của database server
- ✅ Bạn sẽ thấy message: `Using Python from venv: .../database/.venv/bin/python` khi kết nối thành công

## Ví Dụ Workflow

### Bước 1: Kết nối Database
Sau khi chạy client, **đầu tiên** bạn cần kết nối database:

```
Query: Connect to database: host=localhost, port=5432, database=myapp_db, username=postgres, password=mypassword
```

Hoặc bằng tiếng Việt:
```
Query: Kết nối database với host localhost, port 5432, database testdb, username postgres, password 123456
```

### Bước 2: Sử dụng các thao tác CRUD

Sau khi kết nối thành công, bạn có thể:

**Tạo bảng:**
- "Create a table called users with id SERIAL, name VARCHAR(100), email VARCHAR(255), primary key id"

**Thêm dữ liệu:**
- "Insert a new user: name='Alice', email='alice@example.com'"
- "Add user with name Bob and email bob@example.com"

**Truy vấn:**
- "Show me all users"
- "Get users where email contains '@gmail.com'"
- "Select name and email from users where id > 5"

**Cập nhật:**
- "Update user with id=1, set name='Alice Smith'"
- "Change email to 'newemail@example.com' for user where name='Alice'"

**Xóa:**
- "Delete user where id=1"
- "Remove all users where age < 18"

**Quản lý:**
- "List all tables"
- "Describe the users table"
- "Show me current database connection info"

**SQL tùy chỉnh:**
- "Execute: SELECT COUNT(*) FROM users"
- "Run query: SELECT * FROM products WHERE price BETWEEN 100 AND 500"

AI sẽ tự động phân tích và gọi các tools phù hợp để thực hiện yêu cầu của bạn.

## Lưu Ý

⚠️ **Quan trọng:** Bạn phải kết nối database trước khi thực hiện bất kỳ thao tác nào. Nếu chưa kết nối, các tools sẽ báo lỗi và yêu cầu bạn gọi `connect_database` trước.

