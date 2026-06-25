# Use Case Test: Hệ thống Thương mại Điện tử (E-Commerce)

---

## SCHEMA DATABASE

### 1. Bảng `customers` — Khách hàng
```sql
CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    full_name   VARCHAR(100) NOT NULL,
    email       VARCHAR(150) UNIQUE NOT NULL,
    phone       VARCHAR(20),
    city        VARCHAR(50),
    created_at  TIMESTAMP DEFAULT NOW()
);
```

### 2. Bảng `categories` — Danh mục sản phẩm (tự tham chiếu)
```sql
CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    parent_id   INT REFERENCES categories(id)  -- NULL = danh mục cha
);
```

### 3. Bảng `products` — Sản phẩm
```sql
CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    price       DECIMAL(12, 2) NOT NULL,
    stock       INT DEFAULT 0,
    category_id INT REFERENCES categories(id)
);
```

### 4. Bảng `suppliers` — Nhà cung cấp
```sql
CREATE TABLE suppliers (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(150) NOT NULL,
    email   VARCHAR(150),
    phone   VARCHAR(20),
    country VARCHAR(50)
);
```

### 5. Bảng `product_suppliers` — Quan hệ N-N: Sản phẩm ↔ Nhà cung cấp
```sql
CREATE TABLE product_suppliers (
    product_id   INT REFERENCES products(id),
    supplier_id  INT REFERENCES suppliers(id),
    supply_price DECIMAL(12, 2),
    PRIMARY KEY (product_id, supplier_id)
);
```

### 6. Bảng `orders` — Đơn hàng
```sql
CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT REFERENCES customers(id),
    status       VARCHAR(20) DEFAULT 'pending',  -- pending, paid, shipped, cancelled
    total_amount DECIMAL(12, 2),
    created_at   TIMESTAMP DEFAULT NOW()
);
```

### 7. Bảng `order_items` — Chi tiết đơn hàng
```sql
CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT REFERENCES orders(id),
    product_id  INT REFERENCES products(id),
    quantity    INT NOT NULL,
    unit_price  DECIMAL(12, 2) NOT NULL
);
```

### 8. Bảng `reviews` — Đánh giá sản phẩm
```sql
CREATE TABLE reviews (
    id          SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    product_id  INT REFERENCES products(id),
    rating      INT CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

---

## SƠ ĐỒ QUAN HỆ

```
categories (self-ref: parent_id)
     │
     └──< products >──┤ product_suppliers ├──< suppliers
                      │
              order_items >──< orders >──── customers
                      │                         │
                   reviews ───────────────────── ┘
```

**Quan hệ:**
- `categories` → `categories` : 1-N tự tham chiếu (danh mục cha/con)
- `categories` → `products` : 1-N
- `products` ↔ `suppliers` : N-N qua `product_suppliers`
- `customers` → `orders` : 1-N
- `orders` → `order_items` : 1-N
- `products` → `order_items` : 1-N
- `customers` → `reviews` : 1-N
- `products` → `reviews` : 1-N

---

## BỘ PROMPT TEST SQL GENERATION

### 🟢 CẤP ĐỘ 1 — Cơ bản (Basic SELECT, Filter, Sort)

**P01.** Lấy danh sách tất cả khách hàng, sắp xếp theo tên từ A đến Z.

**P02.** Tìm tất cả sản phẩm có giá dưới 500,000 VNĐ và còn hàng trong kho (stock > 0).

**P03.** Lấy 10 sản phẩm đắt nhất.

**P04.** Tìm tất cả đơn hàng có trạng thái là "shipped".

**P05.** Đếm tổng số khách hàng đến từ thành phố "Hà Nội".

---

### 🟡 CẤP ĐỘ 2 — JOIN 2 bảng

**P06.** Lấy danh sách đơn hàng kèm tên khách hàng đặt hàng.

**P07.** Hiển thị tên sản phẩm và tên danh mục của từng sản phẩm.

**P08.** Lấy tất cả sản phẩm chưa có ai đánh giá (review).

**P09.** Tìm tên khách hàng chưa từng đặt đơn hàng nào.

**P10.** Lấy danh sách đơn hàng kèm tổng số lượng sản phẩm trong từng đơn.

---

### 🟠 CẤP ĐỘ 3 — JOIN nhiều bảng + Aggregation

**P11.** Lấy danh sách chi tiết đơn hàng: tên khách hàng, tên sản phẩm, số lượng, đơn giá, thành tiền.

**P12.** Tính tổng doanh thu theo từng tháng trong năm 2024.

**P13.** Lấy top 5 sản phẩm bán chạy nhất (theo tổng số lượng đã bán).

**P14.** Lấy top 5 khách hàng mua nhiều tiền nhất (tổng giá trị các đơn hàng đã thanh toán - status = 'paid').

**P15.** Tính điểm đánh giá trung bình của từng sản phẩm, chỉ lấy sản phẩm có ít nhất 3 đánh giá.

**P16.** Lấy danh sách nhà cung cấp kèm số lượng sản phẩm họ cung cấp.

**P17.** Lấy danh mục cha và số lượng danh mục con bên dưới.

---

### 🔴 CẤP ĐỘ 4 — Subquery, CTE, Window Function

**P18.** Tìm những sản phẩm có giá cao hơn giá trung bình của danh mục mà chúng thuộc về.

**P19.** Lấy khách hàng đã mua nhiều hơn 3 đơn hàng và tổng chi tiêu của họ vượt 5,000,000 VNĐ.

**P20.** Với mỗi khách hàng, lấy đơn hàng gần nhất (mới nhất) của họ kèm trạng thái.

**P21.** Xếp hạng sản phẩm trong từng danh mục theo doanh thu (dùng RANK() hoặc ROW_NUMBER()).

**P22.** Tìm cặp sản phẩm nào thường được mua cùng nhau trong cùng một đơn hàng (xuất hiện ≥ 2 lần).

**P23.** Tính tỷ lệ phần trăm doanh thu của từng danh mục so với tổng doanh thu toàn hệ thống.

**P24.** Lấy lịch sử mua hàng của khách hàng ID = 5, bao gồm: tên sản phẩm, ngày mua, số lượng, đơn giá, điểm đánh giá (nếu có).

---

### 🟣 CẤP ĐỘ 5 — Phức tạp cao / Edge Cases

**P25.** Tìm sản phẩm nào chưa bao giờ được bán (không xuất hiện trong bất kỳ order_items nào) nhưng vẫn còn tồn kho.

**P26.** Lấy danh sách khách hàng đã đánh giá sản phẩm nhưng chưa từng mua sản phẩm đó (dữ liệu bất thường).

**P27.** Tính running total (tổng tích lũy) doanh thu theo ngày trong tháng 6/2024.

**P28.** Với mỗi nhà cung cấp, lấy sản phẩm có supply_price thấp nhất mà họ cung cấp.

**P29.** Lấy toàn bộ cây danh mục (đệ quy từ cha → con → cháu) dùng WITH RECURSIVE.

**P30.** Phát hiện đơn hàng có tổng tiền trong bảng `orders` (total_amount) không khớp với tổng tính từ `order_items` (quantity × unit_price).

---

## GỢI Ý CÁCH TEST

| Nhóm kiểm tra | Prompts đề xuất |
|---|---|
| Smoke test (nhanh) | P01, P02, P06, P11 |
| JOIN logic | P06 – P10 |
| Aggregation | P12 – P17 |
| Subquery / CTE | P18 – P24 |
| Edge cases & data quality | P25 – P30 |
| Toàn bộ | P01 – P30 |

---

## DỮ LIỆU MẪU (INSERT)

```sql
-- Categories
INSERT INTO categories (name, parent_id) VALUES
('Điện tử', NULL),
('Thời trang', NULL),
('Điện thoại', 1),
('Laptop', 1),
('Áo', 2),
('Quần', 2);

-- Suppliers
INSERT INTO suppliers (name, email, country) VALUES
('TechViet', 'contact@techviet.vn', 'Vietnam'),
('Samsung VN', 'b2b@samsung.vn', 'Korea'),
('FashionCo', 'info@fashionco.com', 'China');

-- Products
INSERT INTO products (name, price, stock, category_id) VALUES
('iPhone 15', 22000000, 50, 3),
('Samsung Galaxy S24', 18000000, 30, 3),
('MacBook Pro M3', 45000000, 15, 4),
('Áo thun basic', 150000, 200, 5),
('Quần jeans slim', 350000, 100, 6);

-- Customers
INSERT INTO customers (full_name, email, city) VALUES
('Nguyễn Văn A', 'a@email.com', 'Hà Nội'),
('Trần Thị B', 'b@email.com', 'TP.HCM'),
('Lê Văn C', 'c@email.com', 'Đà Nẵng'),
('Phạm Thị D', 'd@email.com', 'Hà Nội'),
('Hoàng Văn E', 'e@email.com', 'TP.HCM');

-- Orders
INSERT INTO orders (customer_id, status, total_amount) VALUES
(1, 'paid', 22000000),
(1, 'shipped', 45000000),
(2, 'paid', 18000000),
(3, 'pending', 500000),
(4, 'paid', 22150000),
(5, 'cancelled', 350000);

-- Order Items
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
(1, 1, 1, 22000000),
(2, 3, 1, 45000000),
(3, 2, 1, 18000000),
(4, 4, 2, 150000),
(4, 5, 1, 350000) ,  -- tổng = 650000 (không khớp với orders.total_amount=500000 → dùng để test P30)
(5, 1, 1, 22000000),
(5, 4, 1, 150000),
(6, 5, 1, 350000);

-- Reviews
INSERT INTO reviews (customer_id, product_id, rating, comment) VALUES
(1, 1, 5, 'Rất tốt'),
(2, 2, 4, 'Ổn'),
(3, 1, 3, 'Bình thường'),
(4, 3, 5, 'Xuất sắc'),
(2, 1, 4, 'Hài lòng'),
(5, 4, 2, 'Chất vải thường');  -- customer 5 review product 4 nhưng chưa mua → test P26

-- Product Suppliers
INSERT INTO product_suppliers (product_id, supplier_id, supply_price) VALUES
(1, 1, 18000000),
(1, 2, 17500000),
(2, 2, 14000000),
(3, 1, 38000000),
(4, 3, 80000),
(5, 3, 200000);
```
