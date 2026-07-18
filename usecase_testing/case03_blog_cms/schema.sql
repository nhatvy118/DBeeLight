-- Case Study 3: Blog / CMS (Simple tier)
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    email       VARCHAR(150) UNIQUE NOT NULL,
    full_name   VARCHAR(150),
    role        VARCHAR(20) DEFAULT 'author',  -- author, editor, admin
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE posts (
    id            SERIAL PRIMARY KEY,
    user_id       INT REFERENCES users(id),
    title         VARCHAR(200) NOT NULL,
    content       TEXT,
    status        VARCHAR(20) DEFAULT 'draft',  -- draft, published
    published_at  TIMESTAMP
);

CREATE TABLE comments (
    id                  SERIAL PRIMARY KEY,
    post_id             INT REFERENCES posts(id),
    user_id             INT REFERENCES users(id),
    parent_comment_id   INT REFERENCES comments(id),  -- NULL = top-level comment
    content             TEXT NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE tags (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE post_tags (
    post_id  INT REFERENCES posts(id),
    tag_id   INT REFERENCES tags(id),
    PRIMARY KEY (post_id, tag_id)
);
