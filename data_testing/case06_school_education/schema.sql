-- Case Study 6: School / Education (Medium tier)
CREATE TABLE instructors (
    id          SERIAL PRIMARY KEY,
    full_name   VARCHAR(150) NOT NULL,
    department  VARCHAR(100),
    email       VARCHAR(150) UNIQUE NOT NULL
);

CREATE TABLE students (
    id                SERIAL PRIMARY KEY,
    full_name         VARCHAR(150) NOT NULL,
    dob               DATE,
    enrollment_year   INT,
    email             VARCHAR(150) UNIQUE NOT NULL
);

CREATE TABLE courses (
    id             SERIAL PRIMARY KEY,
    title          VARCHAR(150) NOT NULL,
    credits        INT DEFAULT 3,
    instructor_id  INT REFERENCES instructors(id)
);

CREATE TABLE enrollments (
    id           SERIAL PRIMARY KEY,
    student_id   INT REFERENCES students(id),
    course_id    INT REFERENCES courses(id),
    semester     VARCHAR(20) NOT NULL,  -- e.g. '2026-Spring'
    enrolled_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE grades (
    id               SERIAL PRIMARY KEY,
    enrollment_id    INT REFERENCES enrollments(id),
    assignment_name  VARCHAR(100) NOT NULL,
    score            DECIMAL(5, 2) NOT NULL,
    max_score        DECIMAL(5, 2) DEFAULT 100
);
