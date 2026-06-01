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

### Connection Management

#### `connect_db` ⭐ (BẮT BUỘC ĐẦU TIÊN)
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

#### `get_connection_info`
Xem thông tin kết nối database hiện tại (không hiển thị password).

**Ví dụ:**
- "Show me current database connection info"
- "What database am I connected to?"

#### `disconnect_database`
Ngắt kết nối database hiện tại.

**Ví dụ:**
- "Disconnect from database"
- "Close database connection"

### Database & Schema Management

#### `list_databases`
Liệt kê tất cả databases trên PostgreSQL server.

**Ví dụ:**
- "List all databases"
- "Show me available databases"

#### `create_db_from_spec`
Tạo database schema từ specification text (SQL DDL statements).

**Parameters:**
- `spec_text`: SQL DDL statements để tạo tables, constraints, etc.

**Ví dụ:**
- "Create database from this SQL spec: CREATE TABLE users (...)"
- "Build schema from specification"

#### `get_schema`
Lấy toàn bộ database schema (tất cả tables, columns, constraints, etc.).

**Ví dụ:**
- "Get the complete database schema"
- "Show me all tables and their structure"

#### `generate_schema_doc`
Tạo documentation cho database schema.

**Parameters:**
- `format`: Output format - "text" hoặc "markdown" (default: "text")

**Ví dụ:**
- "Generate schema documentation in markdown format"
- "Create schema doc"

### Table Management

#### `list_tables`
Liệt kê tất cả các bảng trong database.

**Ví dụ:**
- "Show me all tables"
- "List tables in the database"

#### `describe_table`
Xem cấu trúc của một bảng (các cột, kiểu dữ liệu, constraints).

**Parameters:**
- `table_name`: Tên bảng

**Ví dụ:**
- "Describe the users table"
- "Show me the structure of products table"

#### `get_table_stats`
Lấy thống kê về một bảng (số dòng, kích thước, etc.).

**Parameters:**
- `table_name`: Tên bảng

**Ví dụ:**
- "Get statistics for users table"
- "Show me stats about products table"

#### `preview_table`
Xem preview của một bảng với số dòng giới hạn.

**Parameters:**
- `table_name`: Tên bảng
- `limit`: Số dòng để preview (default: 10)

**Ví dụ:**
- "Preview the users table"
- "Show me first 20 rows of products table"

#### `create_table`
Tạo bảng mới trong database.

**Parameters:**
- `table_name`: Tên bảng
- `columns`: Định nghĩa các cột (SQL format)
- `primary_key`: (Optional) Tên cột làm primary key

**Ví dụ:**
- "Create a table called users with columns: id SERIAL, name VARCHAR(100), email VARCHAR(255)"
- "Create table products with id SERIAL, name VARCHAR(200), price DECIMAL(10,2), primary key id"

#### `manage_constraint`
Quản lý constraints (thêm, xóa) trên một bảng.

**Parameters:**
- `action`: "add" hoặc "drop"
- `table_name`: Tên bảng
- `constraint_name`: Tên constraint
- `constraint_def`: Định nghĩa constraint (required khi "add", e.g., "CHECK (age > 0)")

**Ví dụ:**
- "Add constraint check_age on users table: CHECK (age > 0)"
- "Drop constraint check_age from users table"

#### `manage_trigger`
Quản lý triggers (tạo, xóa) trên một bảng.

**Parameters:**
- `action`: "create" hoặc "drop"
- `trigger_name`: Tên trigger
- `table_name`: Tên bảng
- `trigger_def`: Định nghĩa trigger (required khi "create")

**Ví dụ:**
- "Create trigger before_insert on users table"
- "Drop trigger before_insert from users table"

### CRUD Operations

#### `insert_data`
Thêm dữ liệu vào bảng.

**Parameters:**
- `table_name`: Tên bảng
- `data`: Dictionary với key là tên cột, value là giá trị

**Ví dụ:**
- "Insert into users: name='John', email='john@example.com'"
- "Add a new product: name='Laptop', price=999.99"

#### `select_data`
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

#### `update_data`
Cập nhật dữ liệu trong bảng.

**Parameters:**
- `table_name`: Tên bảng
- `data`: Dictionary với các giá trị mới
- `where_clause`: Điều kiện WHERE để xác định dòng cần update

**Ví dụ:**
- "Update users set email='newemail@example.com' where id=1"
- "Change product price to 899.99 where name='Laptop'"

#### `delete_data`
Xóa dữ liệu từ bảng.

**Parameters:**
- `table_name`: Tên bảng
- `where_clause`: Điều kiện WHERE để xác định dòng cần xóa

**Ví dụ:**
- "Delete from users where id=1"
- "Remove all products where price < 10"

### SQL Operations

#### `execute_query`
Thực thi một SQL query tùy chỉnh.

**Parameters:**
- `query`: SQL query

**Ví dụ:**
- "Execute: SELECT COUNT(*) FROM users"
- "Run this query: SELECT * FROM products WHERE price BETWEEN 100 AND 500"

#### `validate_sql`
Validate SQL syntax mà không thực thi.

**Parameters:**
- `sql`: SQL query để validate

**Ví dụ:**
- "Validate this SQL: SELECT * FROM users"
- "Check if this query is valid"

#### `explain_sql`
Xem execution plan của một SQL query.

**Parameters:**
- `sql`: SQL query để explain

**Ví dụ:**
- "Explain this query: SELECT * FROM users WHERE age > 18"
- "Show me the execution plan for this SQL"

#### `run_mutation`
Chạy mutation query (INSERT, UPDATE, DELETE) và trả về số dòng bị ảnh hưởng.

**Parameters:**
- `sql`: SQL mutation query (INSERT, UPDATE, hoặc DELETE)

**Ví dụ:**
- "Run mutation: INSERT INTO users (name) VALUES ('John')"
- "Execute this update: UPDATE products SET price = 100 WHERE id = 1"

## Sử Dụng

### Chạy Server (nếu muốn test riêng):
```bash
cd database
uv run database.py
```

### Sử dụng qua API server (khuyến nghị):
- Database server được kết nối bởi `api-server` thông qua package `mcp_agent`.
- Hãy chạy `api-server` và gọi `/api/chat` để sử dụng.

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

### Bước 2: Sử dụng các thao tác

Sau khi kết nối thành công, bạn có thể:

**Quản lý Database & Schema:**
- "List all databases"
- "Get the complete database schema"
- "Generate schema documentation in markdown"

**Quản lý Tables:**
- "List all tables"
- "Describe the users table"
- "Get statistics for products table"
- "Preview the users table with 20 rows"
- "Create a table called users with columns: id SERIAL, name VARCHAR(100), email VARCHAR(255)"

**CRUD Operations:**
- "Insert a new user: name='Alice', email='alice@example.com'"
- "Show me all users"
- "Get users where age > 18"
- "Update user with id=1, set name='Alice Smith'"
- "Delete user where id=1"

**SQL Operations:**
- "Execute: SELECT COUNT(*) FROM users"
- "Validate this SQL query"
- "Explain the execution plan for this query"
- "Run mutation: UPDATE products SET price = 100"

AI sẽ tự động phân tích và gọi các tools phù hợp để thực hiện yêu cầu của bạn.

## Lưu Ý

 **Quan trọng:** Bạn phải kết nối database trước khi thực hiện bất kỳ thao tác nào. Nếu chưa kết nối, các tools sẽ báo lỗi và yêu cầu bạn gọi `connect_db` trước.
