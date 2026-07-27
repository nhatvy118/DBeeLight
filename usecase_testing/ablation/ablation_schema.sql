-- Ablation test schema with abbreviated column names.
-- Column mapping: cust_nm=full_name, crt_ts=created_at, par_id=parent_id,
-- inv_qty=stock, cat_id=category_id, sup_prc=supply_price, sts_cd=status,
-- ord_amt=total_amount, u_prc=unit_price, cust_rtg=rating, cmt=comment

CREATE TABLE custs (
    id        INTEGER PRIMARY KEY,
    cust_nm   TEXT NOT NULL,
    email     TEXT UNIQUE NOT NULL,
    phone     TEXT,
    city      TEXT,
    crt_ts    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE cats (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    par_id  INTEGER REFERENCES cats(id)
);

CREATE TABLE prods (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    descr   TEXT,
    prc     REAL NOT NULL,
    inv_qty INTEGER DEFAULT 0,
    cat_id  INTEGER REFERENCES cats(id)
);

CREATE TABLE sups (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    email   TEXT,
    phone   TEXT,
    country TEXT
);

CREATE TABLE prod_sup (
    prod_id INTEGER REFERENCES prods(id),
    sup_id  INTEGER REFERENCES sups(id),
    sup_prc REAL,
    PRIMARY KEY (prod_id, sup_id)
);

CREATE TABLE ords (
    id      INTEGER PRIMARY KEY,
    cust_id INTEGER REFERENCES custs(id),
    sts_cd  TEXT DEFAULT 'P',
    ord_amt REAL,
    crt_ts  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ord_lines (
    id      INTEGER PRIMARY KEY,
    ord_id  INTEGER REFERENCES ords(id),
    prod_id INTEGER REFERENCES prods(id),
    qty     INTEGER NOT NULL,
    u_prc   REAL NOT NULL
);

CREATE TABLE rvws (
    id       INTEGER PRIMARY KEY,
    cust_id  INTEGER REFERENCES custs(id),
    prod_id  INTEGER REFERENCES prods(id),
    cust_rtg INTEGER,
    cmt      TEXT,
    crt_ts   TEXT DEFAULT (datetime('now'))
);

-- Mirror of the backend descriptions table.
-- column_name='' means table-level description.
CREATE TABLE _descriptions (
    table_name  TEXT NOT NULL,
    column_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    enum_values TEXT,
    PRIMARY KEY (table_name, column_name)
);
