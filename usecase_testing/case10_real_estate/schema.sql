-- Case Study 10: Real Estate Management (Complex tier)
CREATE TABLE owners (
    id         SERIAL PRIMARY KEY,
    full_name  VARCHAR(150) NOT NULL,
    email      VARCHAR(150) UNIQUE,
    phone      VARCHAR(20)
);

CREATE TABLE agents (
    id         SERIAL PRIMARY KEY,
    full_name  VARCHAR(150) NOT NULL,
    email      VARCHAR(150) UNIQUE,
    phone      VARCHAR(20),
    hire_date  DATE DEFAULT CURRENT_DATE
);

CREATE TABLE properties (
    id             SERIAL PRIMARY KEY,
    owner_id       INT REFERENCES owners(id),
    agent_id       INT REFERENCES agents(id),
    address        VARCHAR(200) NOT NULL,
    property_type  VARCHAR(30),  -- apartment, house, studio, commercial
    bedrooms       INT,
    rent_price     DECIMAL(12, 2) NOT NULL
);

CREATE TABLE tenants (
    id         SERIAL PRIMARY KEY,
    full_name  VARCHAR(150) NOT NULL,
    email      VARCHAR(150) UNIQUE,
    phone      VARCHAR(20)
);

CREATE TABLE leases (
    id             SERIAL PRIMARY KEY,
    property_id    INT REFERENCES properties(id),
    tenant_id      INT REFERENCES tenants(id),
    start_date     DATE NOT NULL,
    end_date       DATE,
    monthly_rent   DECIMAL(12, 2) NOT NULL,
    status         VARCHAR(20) DEFAULT 'active'  -- active, ended, terminated
);

CREATE TABLE payments (
    id            SERIAL PRIMARY KEY,
    lease_id      INT REFERENCES leases(id),
    payment_date  DATE NOT NULL,
    amount        DECIMAL(12, 2) NOT NULL,
    payment_method VARCHAR(30)  -- bank_transfer, cash, card
);

CREATE TABLE maintenance_requests (
    id            SERIAL PRIMARY KEY,
    property_id   INT REFERENCES properties(id),
    tenant_id     INT REFERENCES tenants(id),
    request_date  DATE DEFAULT CURRENT_DATE,
    description   VARCHAR(200),
    status        VARCHAR(20) DEFAULT 'open'  -- open, in_progress, resolved
);
