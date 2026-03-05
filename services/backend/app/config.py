"""
============================================================================
FILE: services/backend/app/config.py
PURPOSE: Combined configuration for Auth, BFF, and Ingest functionality.
DEPENDENCIES: pydantic-settings
============================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # Base configuration
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "backend-svc"
    service_version: str = "1.0.0"

    # JWT configuration (Auth & BFF)
    jwt_secret: str
    jwt_expiry_hours: int = 8

    # Static account credentials (bcrypt hashes from environment)
    admin_username: str = "hr_admin"
    admin_password_hash: str
    user_username: str = "hr_user"
    user_password_hash: str

    # PostgreSQL (Audit, Auth, BFF, Ingest)
    postgres_dsn: str

    # Redis (Semantic cache + Celery broker)
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # MinIO (Ingest)
    minio_endpoint_url: str = "http://minio:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str
    minio_bucket_name: str = "hr-documents"

    # Qdrant (Ingest worker)
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "hr_documents"

    # Internal Service URLs
    rag_pipeline_url: str = "http://rag-pipeline:8002"
    embedding_svc_url: str = "http://rag-pipeline:8002"

    # Document processing parameters
    max_upload_size_mb: int = 200
    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 64
    tesseract_lang: str = "eng+ara"
    embedding_dense_dim: int = 1024  # BGE-M3 dense vector dimension


settings = BackendSettings()
