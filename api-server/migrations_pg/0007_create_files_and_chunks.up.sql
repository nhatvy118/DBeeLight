-- pgvector + session-attached files + chunks for RAG
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(google_sub) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    local_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    sqlite_table_name TEXT,
    sqlite_db_path TEXT,
    summary TEXT,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS files_session_id_idx ON files (session_id);
CREATE INDEX IF NOT EXISTS files_user_id_idx ON files (user_id);

CREATE TABLE IF NOT EXISTS file_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS file_chunks_session_id_idx ON file_chunks (session_id);
CREATE INDEX IF NOT EXISTS file_chunks_file_id_idx ON file_chunks (file_id);

CREATE INDEX IF NOT EXISTS file_chunks_embedding_hnsw ON file_chunks
    USING hnsw (embedding vector_cosine_ops);
