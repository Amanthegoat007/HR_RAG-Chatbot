-- ============================================================================
-- FILE: db/init.sql
-- PURPOSE: PostgreSQL schema initialization for the HR RAG Chatbot system.
--          Runs automatically on first container start via docker-entrypoint-initdb.d/
-- ARCHITECTURE REF: §7 — Database Schema (PostgreSQL)
-- DEPENDENCIES: PostgreSQL 16
-- ============================================================================

-- Enable UUID generation (built-in in PostgreSQL 13+, uses gen_random_uuid())
-- No extension needed — gen_random_uuid() is available by default

-- ===========================================================================
-- TABLE: documents
-- Tracks every document uploaded to the system.
-- One row per file upload. Status progresses:
-- queued/pending -> normalizing/processing/embedding -> ready | failed | needs_review
-- ===========================================================================
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename            VARCHAR(500) NOT NULL,
    original_format     VARCHAR(10) NOT NULL
                            CHECK (original_format IN ('pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md')),
    -- MinIO path to the intermediate Markdown version (null until processing completes)
    -- Stored for debugging and audit: admins can inspect converted markdown quality
    markdown_path       VARCHAR(1000),
    -- MinIO path to the original uploaded file
    minio_path          VARCHAR(1000) NOT NULL,
    file_size_bytes     BIGINT NOT NULL,
    page_count          INTEGER,       -- extracted during markdown conversion
    chunk_count         INTEGER DEFAULT 0,  -- updated after Qdrant upsert completes
    status              VARCHAR(20) DEFAULT 'pending'
                            CHECK (status IN ('queued', 'pending', 'normalizing', 'processing', 'embedding', 'ready', 'failed', 'needs_review')),
    uploaded_by         VARCHAR(50) DEFAULT 'hr_admin',
    uploaded_at         TIMESTAMPTZ DEFAULT NOW(),
    processed_at        TIMESTAMPTZ,   -- set when status becomes 'ready' or 'failed'
    error_message       TEXT,          -- populated only when status = 'failed'
    -- Flexible metadata bag: stores extracted headings, section names, etc.
    -- Used for better citation attribution in RAG responses
    metadata            JSONB DEFAULT '{}'::jsonb,
    -- Optimistic locking version for concurrent updates
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===========================================================================
-- TABLE: ingestion_jobs
-- Tracks the Celery task lifecycle for each document processing job.
-- Linked to documents table via document_id foreign key.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status                  VARCHAR(20) DEFAULT 'queued'
                                CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    -- Celery task ID for monitoring via Celery Flower or direct Redis inspection
    celery_task_id          VARCHAR(255),
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    error_message           TEXT,
    processing_time_seconds FLOAT,      -- computed as (completed_at - started_at)
    -- Breakdown of processing stages for debugging (stored as JSON)
    -- e.g.: {"conversion_s": 2.1, "chunking_s": 0.3, "embedding_s": 15.2, "upsert_s": 0.8}
    stage_timings           JSONB DEFAULT '{}'::jsonb
);

-- ===========================================================================
-- TABLE: audit_log
-- Immutable log of security-relevant events.
-- 90-day retention policy (see maintenance note below).
-- Architecture §9: every login attempt, upload, deletion → logged here.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    event_type  VARCHAR(50) NOT NULL
                    CHECK (event_type IN (
                        'login_success',
                        'login_failure',
                        'upload_start',
                        'upload_complete',
                        'upload_failed',
                        'document_delete',
                        'document_delete_failed',
                        'query',
                        'cache_hit',
                        'ingestion_start',
                        'ingestion_complete',
                        'ingestion_failed'
                    )),
    role        VARCHAR(10)  -- 'admin' or 'user'; null for unauthenticated events
                    CHECK (role IS NULL OR role IN ('admin', 'user')),
    username    VARCHAR(50), -- null for failed logins (unknown user)
    ip_address  VARCHAR(45), -- IPv4 or IPv6
    -- Event-specific details. Examples:
    -- login_success:    {"username": "hr_admin"}
    -- upload_complete:  {"filename": "policy.pdf", "document_id": "uuid", "chunk_count": 45}
    -- query:            {"question_length": 85, "cache_hit": false, "response_ms": 2340}
    -- document_delete:  {"document_id": "uuid", "filename": "policy.pdf"}
    details     JSONB DEFAULT '{}'::jsonb,
    -- created_at kept separate from timestamp for partitioning flexibility
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ===========================================================================
-- INDEXES — Optimized for common query patterns
-- ===========================================================================

-- documents: most queries filter by status or order by upload date
CREATE INDEX idx_documents_status
    ON documents(status);

CREATE INDEX idx_documents_uploaded_at
    ON documents(uploaded_at DESC);

-- Support fast lookup by filename (admin UI search)
CREATE INDEX idx_documents_filename
    ON documents(filename);

-- ingestion_jobs: look up jobs by document ID (FK traversal)
CREATE INDEX idx_ingestion_jobs_document_id
    ON ingestion_jobs(document_id);

CREATE INDEX idx_ingestion_jobs_status
    ON ingestion_jobs(status);

CREATE INDEX idx_ingestion_jobs_celery_task_id
    ON ingestion_jobs(celery_task_id)
    WHERE celery_task_id IS NOT NULL;

-- audit_log: most queries filter by timestamp (range) or event_type
CREATE INDEX idx_audit_log_timestamp
    ON audit_log(timestamp DESC);

CREATE INDEX idx_audit_log_event_type
    ON audit_log(event_type);

CREATE INDEX idx_audit_log_ip_address
    ON audit_log(ip_address)
    WHERE ip_address IS NOT NULL;

-- ===========================================================================
-- RETENTION POLICY NOTE
-- Run this via a daily cron job or pg_cron extension to enforce 90-day retention:
--   DELETE FROM audit_log WHERE timestamp < NOW() - INTERVAL '90 days';
-- For production, consider pg_partman for automated partition management.
-- ===========================================================================

-- ===========================================================================
-- GRANT PERMISSIONS
-- The application user (hr_rag_user) needs full CRUD on all tables
-- ===========================================================================
GRANT ALL PRIVILEGES ON TABLE documents TO CURRENT_USER;
GRANT ALL PRIVILEGES ON TABLE ingestion_jobs TO CURRENT_USER;
GRANT ALL PRIVILEGES ON TABLE audit_log TO CURRENT_USER;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO CURRENT_USER;

-- ===========================================================================
-- TABLE: conversations
-- Tracks chat sessions for users.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(50) NOT NULL,
    title       VARCHAR(200) NOT NULL DEFAULT 'New Chat',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to auto-update updated_at for conversations
CREATE TRIGGER conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===========================================================================
-- TABLE: messages
-- Tracks individual messages within a conversation.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast retrieval
CREATE INDEX idx_conversations_user ON conversations(user_id, created_at DESC);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at ASC);

-- Grant privileges for new tables
GRANT ALL PRIVILEGES ON TABLE conversations TO CURRENT_USER;
GRANT ALL PRIVILEGES ON TABLE messages TO CURRENT_USER;

-- Verify schema was created
DO $$
BEGIN
    RAISE NOTICE 'HR RAG Chatbot schema initialized successfully.';
    RAISE NOTICE 'Tables created: documents, ingestion_jobs, audit_log, conversations, messages';
END $$;
