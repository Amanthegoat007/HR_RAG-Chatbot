from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # Base configuration
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "rag-pipeline-svc"
    service_version: str = "1.0.0"

    # Redis (Semantic cache)
    redis_url: str = "redis://redis:6379/0"

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "hr_documents"

    # ─── LLM Configuration ────────────────────────────────────────────────
    llm_server_url: str = "http://localhost:8080"
    llm_circuit_breaker_threshold: int = 5
    llm_circuit_breaker_recovery_seconds: int = 60
    llm_provider: str = "local"  # "local" | "azure_openai"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 256
    llm_max_tokens_short: int = 120
    llm_max_tokens_medium: int = 180
    llm_max_tokens_long: int = 256
    llm_top_p: float = 0.95
    llm_stop_sequence: str = "<END_ANSWER>"
    llm_adaptive_tokens_enabled: bool = True
    llm_stream_timeout_seconds: float = 300.0
    prompt_max_chunks: int = 2
    prompt_max_chunk_chars: int = 450
    prompt_max_chunk_sentences: int = 4

    # Azure OpenAI fallback (optional)
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_deployment_id: str = "gpt-4o"
    azure_openai_api_version: str = "2024-02-01"

    # ─── Embedding Model (In-Process BGE-M3) ──────────────────────────────
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_batch_size: int = 32
    embedding_max_length: int = 8192
    embedding_svc_url: str = "http://localhost:8004"  # Legacy, unused in consolidated mode

    # ─── Reranker Model (In-Process BGE-Reranker) ─────────────────────────
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_max_length: int = 512
    reranker_batch_size: int = 16
    reranker_svc_url: str = "http://localhost:8005"  # Legacy, unused in consolidated mode
    reranker_timeout_seconds: float = 30.0

    # ─── Model Download / Cache Warmup ─────────────────────────────────────
    model_prefetch_on_startup: bool = True
    model_download_workers: int = 16

    # ─── Retrieval & Reranking Pipeline ───────────────────────────────────
    retrieval_rerank_top_n: int = 20
    retrieval_dense_top_k: int = 15
    retrieval_sparse_top_k: int = 15
    hybrid_search_alpha: float = 0.5
    top_k_retrieval: int = 20
    top_n_rerank: int = 3
    score_threshold: float = 0.2

    # ─── Semantic Cache ───────────────────────────────────────────────
    cache_similarity_threshold: float = 0.92
    cache_ttl_seconds: int = 86400  # 24 hours

settings = RagSettings()
