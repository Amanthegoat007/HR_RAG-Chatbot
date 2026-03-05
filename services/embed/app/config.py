"""
============================================================================
FILE: services/embed/app/config.py
PURPOSE: Configuration settings for the embedding service loaded from
         environment variables at startup.
ARCHITECTURE REF: §3.3 — BGE-M3 Optimization for CPU
DEPENDENCIES: pydantic-settings
============================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    """
    Settings loaded from environment variables.

    Pydantic-settings automatically reads from environment variables
    (case-insensitive) and from the .env file if present.
    All values have sensible defaults matching docker-compose.yml.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Model configuration
    embedding_model_name: str = "BAAI/bge-m3"
    # BGE-M3 produces 1024-dimensional dense vectors
    embedding_dense_dim: int = 1024
    # Batch size for inference (BGE-M3 is efficient at batch_size=32 on CPU)
    embedding_batch_size: int = 32
    # Maximum sequence length (BGE-M3 supports up to 8192 tokens, but 512 is typical for chunks)
    embedding_max_length: int = 512

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8004
    log_level: str = "INFO"
    log_format: str = "json"

    # Service identity (used in health check response and logs)
    service_name: str = "embedding-svc"
    service_version: str = "1.0.0"


# Singleton settings instance — import this in other modules
settings = EmbeddingSettings()
