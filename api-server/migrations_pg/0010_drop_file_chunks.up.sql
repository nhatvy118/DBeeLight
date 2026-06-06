-- Remove vector RAG storage (SQL-first uses files + SQLite only).
DROP INDEX IF EXISTS file_chunks_embedding_hnsw;
DROP INDEX IF EXISTS file_chunks_file_id_idx;
DROP INDEX IF EXISTS file_chunks_session_id_idx;
DROP TABLE IF EXISTS file_chunks;
