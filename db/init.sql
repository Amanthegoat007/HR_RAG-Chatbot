CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    title TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    original_format VARCHAR(50) NOT NULL,
    minio_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    uploaded_by VARCHAR(255) NOT NULL,
    metadata JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    markdown_path VARCHAR(500),
    page_count INT,
    chunk_count INT,
    error_message TEXT,
    processed_at TIMESTAMP WITH TIME ZONE,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    celery_task_id VARCHAR(255),
    status VARCHAR(50) DEFAULT 'queued',
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    processing_time_seconds DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(255) NOT NULL,
    role VARCHAR(255),
    username VARCHAR(255),
    ip_address VARCHAR(255),
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION update_conversation_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations SET updated_at = NOW() WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_conversation_timestamp ON messages;
CREATE TRIGGER trg_update_conversation_timestamp
AFTER INSERT ON messages
FOR EACH ROW
EXECUTE FUNCTION update_conversation_timestamp();
