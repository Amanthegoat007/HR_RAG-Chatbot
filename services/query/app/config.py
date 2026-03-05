"""
============================================================================
FILE: services/query/app/config.py
PURPOSE: Configuration for the query service loaded from environment variables.
ARCHITECTURE REF: §4 — RAG Query Pipeline
DEPENDENCIES: pydantic-settings
============================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class QuerySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # JWT
    jwt_secret: str

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "hr_documents"

    # Redis cache
    redis_url: str = "redis://redis:6379/0"
    redis_cache_db: int = 0
    cache_similarity_threshold: float = 0.92
    cache_max_entries: int = 1000
    cache_ttl_seconds: int = 86400  # 24 hours

    # Embedding service
    embedding_svc_url: str = "http://embedding-svc:8004"

    # Reranker service
    reranker_svc_url: str = "http://reranker-svc:8005"
    reranker_top_n: int = 5  # Return top-5 after reranking
    reranker_timeout_seconds: float = 10.0

    # LLM
    llm_provider: str = "local"           # local | azure_openai | openai
    llm_server_url: str = "http://llm-server:8080"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.1
    llm_top_p: float = 0.95
    llm_timeout_seconds: int = 60
    llm_stream_timeout_seconds: int = 120
    llm_circuit_breaker_threshold: int = 5
    llm_circuit_breaker_recovery_seconds: int = 30

    # Azure OpenAI (optional fallback)
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-02-01"

    # OpenAI (optional fallback)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Retrieval parameters
    retrieval_dense_top_k: int = 15
    retrieval_sparse_top_k: int = 15
    retrieval_rerank_top_n: int = 20    # Send top-20 to reranker
    rrf_k_constant: int = 60           # RRF constant (standard = 60)

    # Service
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "query-svc"
    service_version: str = "1.0.0"


settings = QuerySettings()
