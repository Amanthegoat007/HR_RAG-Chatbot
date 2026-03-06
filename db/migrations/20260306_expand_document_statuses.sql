-- Expand documents.status allowed values for staged ingestion + quarantine.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;

ALTER TABLE documents
ADD CONSTRAINT documents_status_check
CHECK (
    status IN (
        'queued',
        'pending',
        'normalizing',
        'processing',
        'embedding',
        'ready',
        'failed',
        'needs_review'
    )
);

