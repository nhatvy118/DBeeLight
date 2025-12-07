# Ví Dụ Sử Dụng Database Server

## Workflow Hoàn Chỉnh

### 1. Khởi động Client
```bash
cd mcp-client
uv run client.py ../database/database.py
```

### 2. Kết Nối Database (Bước đầu tiên)

**Query:**
```
Connect to database: host=localhost, port=5432, database=postgres, username=postgres, password=110804
```

**Hoặc tiếng Việt:**
```
Kết nối database với host localhost, port 5432, database testdb, username postgres, password mypassword
```

**Kết quả:**
```
Successfully connected to database 'testdb' on localhost:5432 as user 'postgres'.
```

### 3. Tạo Bảng

**Query:**
```
Create a table called users with columns: id SERIAL, name VARCHAR(100), email VARCHAR(255) UNIQUE, age INTEGER, primary key id
```

**Kết quả:**
```
Table 'users' created successfully.
```

### 4. Thêm Dữ Liệu

**Query:**
```
Insert into users: name='Alice', email='alice@example.com', age=25
```

**Kết quả:**
```
Data inserted successfully into 'users'. Inserted row: {'id': 1, 'name': 'Alice', 'email': 'alice@example.com', 'age': 25}
```

**Thêm nhiều users:**
```
Insert user: name='Bob', email='bob@example.com', age=30
Insert user: name='Charlie', email='charlie@example.com', age=28
```

### 5. Truy Vấn Dữ Liệu

**Query:**
```
Show me all users
```

**Kết quả:**
```
Found 3 row(s):
[{'id': 1, 'name': 'Alice', 'email': 'alice@example.com', 'age': 25}, {'id': 2, 'name': 'Bob', 'email': 'bob@example.com', 'age': 30}, {'id': 3, 'name': 'Charlie', 'email': 'charlie@example.com', 'age': 28}]
```

**Query với điều kiện:**
```
Get users where age > 25
```

**Kết quả:**
```
Found 2 row(s):
[{'id': 2, 'name': 'Bob', 'email': 'bob@example.com', 'age': 30}, {'id': 3, 'name': 'Charlie', 'email': 'charlie@example.com', 'age': 28}]
```

**Query với limit:**
```
Show me the first 2 users ordered by name
```

### 6. Cập Nhật Dữ Liệu

**Query:**
```
Update users set age=26 where id=1
```

**Hoặc:**
```
Change age to 26 for user with name='Alice'
```

**Kết quả:**
```
Updated 1 row(s) in 'users':
[{'id': 1, 'name': 'Alice', 'email': 'alice@example.com', 'age': 26}]
```

### 7. Xóa Dữ Liệu

**Query:**
```
Delete from users where id=3
```

**Kết quả:**
```
Deleted 1 row(s) from 'users':
[{'id': 3, 'name': 'Charlie', 'email': 'charlie@example.com', 'age': 28}]
```

### 8. Quản Lý Database

**Liệt kê tables:**
```
List all tables
```

**Kết quả:**
```
Tables in database: users
```

**Xem cấu trúc bảng:**
```
Describe the users table
```

**Kết quả:**
```
Structure of table 'users':
- id: integer NOT NULL
- name: character varying
- email: character varying
- age: integer
```

**Xem thông tin kết nối:**
```
Show me current database connection info
```

**Kết quả:**
```
Current database connection:
- Host: localhost
- Port: 5432
- Database: testdb
- Username: postgres
- Status: Connected
```

### 9. SQL Query Tùy Chỉnh

**Query:**
```
Execute: SELECT COUNT(*) FROM users
```

**Kết quả:**
```
Query returned 1 row(s):
[{'count': 2}]
```

**Query phức tạp:**
```
Run query: SELECT name, email FROM users WHERE age BETWEEN 25 AND 30 ORDER BY name
```

### 10. Ngắt Kết Nối

**Query:**
```
Disconnect from database
```

**Kết quả:**
```
Disconnected from database successfully.
```

## Lưu Ý Quan Trọng

⚠️ **Phải kết nối database trước:** Nếu bạn cố gắng sử dụng các tools khác mà chưa kết nối, bạn sẽ nhận được thông báo:

```
Error creating table: Database not connected. Please use 'connect_database' tool first to provide database credentials (host, port, database name, username, password).
```

✅ **AI tự động hiểu:** Bạn có thể diễn đạt yêu cầu theo nhiều cách khác nhau, AI sẽ tự động parse và gọi tools phù hợp:

- "Tạo bảng users với cột id, name, email"
- "Thêm user mới tên là John"
- "Hiển thị tất cả users"
- "Xóa user có id bằng 1"
- "Cập nhật email của user John thành john.new@example.com"

