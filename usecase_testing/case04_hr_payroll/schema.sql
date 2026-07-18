-- Case Study 4: HR & Payroll (Medium tier)
CREATE TABLE departments (
    id        SERIAL PRIMARY KEY,
    name      VARCHAR(100) NOT NULL,
    location  VARCHAR(100)
);

CREATE TABLE positions (
    id     SERIAL PRIMARY KEY,
    title  VARCHAR(100) NOT NULL,
    level  VARCHAR(20)  -- junior, mid, senior, lead
);

CREATE TABLE employees (
    id              SERIAL PRIMARY KEY,
    full_name       VARCHAR(150) NOT NULL,
    email           VARCHAR(150) UNIQUE NOT NULL,
    department_id   INT REFERENCES departments(id),
    position_id     INT REFERENCES positions(id),
    manager_id      INT REFERENCES employees(id),  -- self-reference, NULL = top of hierarchy
    hire_date       DATE NOT NULL,
    salary          DECIMAL(12, 2) NOT NULL
);

CREATE TABLE attendance (
    id           SERIAL PRIMARY KEY,
    employee_id  INT REFERENCES employees(id),
    work_date    DATE NOT NULL,
    check_in     TIME,
    check_out    TIME,
    status       VARCHAR(20) DEFAULT 'present'  -- present, late, absent, leave
);

CREATE TABLE payroll (
    id             SERIAL PRIMARY KEY,
    employee_id    INT REFERENCES employees(id),
    period_month   VARCHAR(7) NOT NULL,  -- 'YYYY-MM'
    base_salary    DECIMAL(12, 2) NOT NULL,
    bonus          DECIMAL(12, 2) DEFAULT 0,
    deductions     DECIMAL(12, 2) DEFAULT 0,
    net_pay        DECIMAL(12, 2) NOT NULL
);
