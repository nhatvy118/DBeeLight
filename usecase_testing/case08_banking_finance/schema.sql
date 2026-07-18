-- Case Study 8: Banking & Finance (Complex tier)
CREATE TABLE branches (
    id       SERIAL PRIMARY KEY,
    name     VARCHAR(100) NOT NULL,
    city     VARCHAR(100),
    address  VARCHAR(200)
);

CREATE TABLE customers (
    id           SERIAL PRIMARY KEY,
    full_name    VARCHAR(150) NOT NULL,
    email        VARCHAR(150) UNIQUE NOT NULL,
    phone        VARCHAR(20),
    national_id  VARCHAR(20) UNIQUE
);

CREATE TABLE accounts (
    id            SERIAL PRIMARY KEY,
    customer_id   INT REFERENCES customers(id),
    branch_id     INT REFERENCES branches(id),
    account_type  VARCHAR(20) DEFAULT 'checking',  -- checking, savings
    balance       DECIMAL(14, 2) NOT NULL DEFAULT 0,
    opened_at     DATE DEFAULT CURRENT_DATE
);

CREATE TABLE transactions (
    id                SERIAL PRIMARY KEY,
    account_id        INT REFERENCES accounts(id),
    transaction_type  VARCHAR(20) NOT NULL,  -- deposit, withdrawal, transfer
    amount            DECIMAL(14, 2) NOT NULL,
    transaction_date  TIMESTAMP DEFAULT NOW(),
    description       VARCHAR(200)
);

CREATE TABLE cards (
    id            SERIAL PRIMARY KEY,
    account_id    INT REFERENCES accounts(id),
    card_number   VARCHAR(20) UNIQUE NOT NULL,
    card_type     VARCHAR(20) DEFAULT 'debit',  -- debit, credit
    expiry_date   DATE,
    status        VARCHAR(20) DEFAULT 'active'  -- active, blocked, expired
);

CREATE TABLE loans (
    id            SERIAL PRIMARY KEY,
    customer_id   INT REFERENCES customers(id),
    branch_id     INT REFERENCES branches(id),
    loan_amount   DECIMAL(14, 2) NOT NULL,
    interest_rate DECIMAL(5, 2) NOT NULL,
    term_months   INT NOT NULL,
    status        VARCHAR(20) DEFAULT 'active',  -- active, closed, defaulted
    start_date    DATE DEFAULT CURRENT_DATE
);

CREATE TABLE loan_payments (
    id                 SERIAL PRIMARY KEY,
    loan_id            INT REFERENCES loans(id),
    payment_date       DATE NOT NULL,
    amount_paid        DECIMAL(14, 2) NOT NULL,
    remaining_balance  DECIMAL(14, 2) NOT NULL
);
