-- Case Study 7: Restaurant Reservation & Ordering (Medium tier)
CREATE TABLE customers (
    id         SERIAL PRIMARY KEY,
    full_name  VARCHAR(150) NOT NULL,
    phone      VARCHAR(20),
    email      VARCHAR(150) UNIQUE
);

CREATE TABLE tables (
    id            SERIAL PRIMARY KEY,
    table_number  INT UNIQUE NOT NULL,
    capacity      INT NOT NULL,
    location      VARCHAR(50)  -- indoor, outdoor, private room
);

CREATE TABLE reservations (
    id                 SERIAL PRIMARY KEY,
    customer_id        INT REFERENCES customers(id),
    table_id           INT REFERENCES tables(id),
    reservation_time   TIMESTAMP NOT NULL,
    party_size         INT NOT NULL,
    status             VARCHAR(20) DEFAULT 'confirmed'  -- confirmed, seated, cancelled, no_show
);

CREATE TABLE menu_items (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(150) NOT NULL,
    category      VARCHAR(50),  -- appetizer, main, dessert, beverage
    price         DECIMAL(10, 2) NOT NULL,
    is_available  BOOLEAN DEFAULT TRUE
);

CREATE TABLE orders (
    id             SERIAL PRIMARY KEY,
    reservation_id INT REFERENCES reservations(id),
    order_time     TIMESTAMP DEFAULT NOW(),
    status         VARCHAR(20) DEFAULT 'open',  -- open, served, paid
    total_amount   DECIMAL(10, 2)
);

CREATE TABLE order_items (
    id            SERIAL PRIMARY KEY,
    order_id      INT REFERENCES orders(id),
    menu_item_id  INT REFERENCES menu_items(id),
    quantity      INT NOT NULL,
    unit_price    DECIMAL(10, 2) NOT NULL
);
