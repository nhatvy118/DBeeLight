-- Case Study 2: Library Management (Simple tier)
CREATE TABLE authors (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    birth_year  INT,
    nationality VARCHAR(50)
);

CREATE TABLE books (
    id                SERIAL PRIMARY KEY,
    title             VARCHAR(200) NOT NULL,
    isbn              VARCHAR(20) UNIQUE,
    author_id         INT REFERENCES authors(id),
    published_year    INT,
    copies_available  INT DEFAULT 1
);

CREATE TABLE members (
    id              SERIAL PRIMARY KEY,
    full_name       VARCHAR(150) NOT NULL,
    email           VARCHAR(150) UNIQUE NOT NULL,
    join_date       DATE DEFAULT CURRENT_DATE,
    membership_type VARCHAR(20) DEFAULT 'standard'  -- standard, premium
);

CREATE TABLE loans (
    id          SERIAL PRIMARY KEY,
    book_id     INT REFERENCES books(id),
    member_id   INT REFERENCES members(id),
    loan_date   DATE NOT NULL,
    due_date    DATE NOT NULL,
    return_date DATE  -- NULL = not yet returned
);
