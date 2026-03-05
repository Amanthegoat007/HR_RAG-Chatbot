"""
============================================================================
FILE: services/rerank/app/config.py
PURPOSE: Configuration settings for the reranker service.
ARCHITECTURE REF: §4.2 — Reranking
DEPENDENCIES: pydantic-settings
============================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class RerankerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    # Maximum sequence length for query+document pair
    reranker_max_length: int = 1024
    # Batch size for scoring pairs (smaller than embed batch due to higher memory per pair)
    reranker_batch_size: int = 8

    host: str = "0.0.0.0"
    port: int = 8005
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "reranker-svc"
    service_version: str = "1.0.0"


settings = RerankerSettings()
