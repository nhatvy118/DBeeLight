-- Case Study 9: Logistics & Warehouse (Complex tier)
CREATE TABLE warehouses (
    id        SERIAL PRIMARY KEY,
    name      VARCHAR(100) NOT NULL,
    city      VARCHAR(100),
    capacity  INT
);

CREATE TABLE products (
    id        SERIAL PRIMARY KEY,
    name      VARCHAR(150) NOT NULL,
    sku       VARCHAR(30) UNIQUE,
    category  VARCHAR(50)
);

CREATE TABLE inventory (
    id             SERIAL PRIMARY KEY,
    warehouse_id   INT REFERENCES warehouses(id),
    product_id     INT REFERENCES products(id),
    quantity       INT NOT NULL DEFAULT 0,
    last_updated   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE carriers (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    contact_phone  VARCHAR(20)
);

CREATE TABLE routes (
    id                     SERIAL PRIMARY KEY,
    origin_warehouse_id    INT REFERENCES warehouses(id),
    destination_city       VARCHAR(100) NOT NULL,
    distance_km            DECIMAL(8, 2)
);

CREATE TABLE shipments (
    id                    SERIAL PRIMARY KEY,
    origin_warehouse_id   INT REFERENCES warehouses(id),
    carrier_id            INT REFERENCES carriers(id),
    route_id              INT REFERENCES routes(id),
    shipment_date         DATE NOT NULL,
    status                VARCHAR(20) DEFAULT 'pending'  -- pending, in_transit, delivered, delayed
);

CREATE TABLE tracking_events (
    id                   SERIAL PRIMARY KEY,
    shipment_id          INT REFERENCES shipments(id),
    event_time           TIMESTAMP NOT NULL,
    location             VARCHAR(150),
    status_description   VARCHAR(100)  -- e.g. 'departed warehouse', 'arrived at hub', 'out for delivery'
);
