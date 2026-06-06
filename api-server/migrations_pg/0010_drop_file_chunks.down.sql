-- Recreate file_chunks (empty); pgvector extension from 0007 remains.
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
