"""
============================================================================
FILE: services/ingest/app/config.py
PURPOSE: Configuration for both ingest-svc and ingest-worker (same image).
ARCHITECTURE REF: §3 — Document Ingestion Pipeline
DEPENDENCIES: pydantic-settings
============================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # JWT (for protecting upload/delete endpoints)
    jwt_secret: str

    # PostgreSQL
    postgres_dsn: str

    # Redis (semantic cache + Celery broker)
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # MinIO
    minio_endpoint_url: str = "http://minio:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str
    minio_bucket_name: str = "hr-documents"

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "hr_documents"
    embedding_dense_dim: int = 1024

    # Embedding service
    embedding_svc_url: str = "http://embedding-svc:8004"

    # Document processing
    max_upload_size_mb: int = 200
    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 64
    tesseract_lang: str = "eng+ara"

    # Service
    host: str = "0.0.0.0"
    port: int = 8003
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "ingest-svc"
    service_version: str = "1.0.0"


settings = IngestSettings()
