-- Case Study 5: Hospital / Clinic (Medium tier)
CREATE TABLE departments (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(100) NOT NULL
);

CREATE TABLE doctors (
    id             SERIAL PRIMARY KEY,
    full_name      VARCHAR(150) NOT NULL,
    specialty      VARCHAR(100),
    department_id  INT REFERENCES departments(id),
    phone          VARCHAR(20)
);

CREATE TABLE patients (
    id         SERIAL PRIMARY KEY,
    full_name  VARCHAR(150) NOT NULL,
    dob        DATE,
    gender     VARCHAR(10),
    phone      VARCHAR(20),
    address    VARCHAR(200)
);

CREATE TABLE appointments (
    id                SERIAL PRIMARY KEY,
    patient_id        INT REFERENCES patients(id),
    doctor_id         INT REFERENCES doctors(id),
    appointment_time  TIMESTAMP NOT NULL,
    status            VARCHAR(20) DEFAULT 'scheduled',  -- scheduled, completed, cancelled
    reason            VARCHAR(200)
);

CREATE TABLE prescriptions (
    id               SERIAL PRIMARY KEY,
    appointment_id   INT REFERENCES appointments(id),
    medication_name  VARCHAR(150) NOT NULL,
    dosage           VARCHAR(50),
    duration_days    INT
);
