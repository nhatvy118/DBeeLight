-- Case Study 1: E-Commerce (Medium tier) -- baseline, already validated
-- Reproduced from usecase_testing/test_usecase_ecommerce.md
CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    full_name   VARCHAR(100) NOT NULL,
    email       VARCHAR(150) UNIQUE NOT NULL,
    phone       VARCHAR(20),
    city        VARCHAR(50),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    parent_id   INT REFERENCES categories(id)  -- NULL = top-level category
);

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    price       DECIMAL(12, 2) NOT NULL,
    stock       INT DEFAULT 0,
    category_id INT REFERENCES categories(id)
);

CREATE TABLE suppliers (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(150) NOT NULL,
    email   VARCHAR(150),
    phone   VARCHAR(20),
    country VARCHAR(50)
);

CREATE TABLE product_suppliers (
    product_id   INT REFERENCES products(id),
    supplier_id  INT REFERENCES suppliers(id),
    supply_price DECIMAL(12, 2),
    PRIMARY KEY (product_id, supplier_id)
);

CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT REFERENCES customers(id),
    status       VARCHAR(20) DEFAULT 'pending',  -- pending, paid, shipped, cancelled
    total_amount DECIMAL(12, 2),
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT REFERENCES orders(id),
    product_id  INT REFERENCES products(id),
    quantity    INT NOT NULL,
    unit_price  DECIMAL(12, 2) NOT NULL
);

CREATE TABLE reviews (
    id          SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    product_id  INT REFERENCES products(id),
    rating      INT CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);
