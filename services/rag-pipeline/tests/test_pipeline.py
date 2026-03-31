import os
import sys

os.environ.setdefault("JWT_SECRET", "test_secret_key_at_least_256_bits_long_for_testing")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("QDRANT_PORT", "6333")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("EMBEDDING_SVC_URL", "http://localhost:8004")
os.environ.setdefault("RERANKER_SVC_URL", "http://localhost:8005")
os.environ.setdefault("LLM_SERVER_URL", "http://localhost:8080")
os.environ.setdefault("QDRANT_COLLECTION", "hr_documents")

sys.path.insert(0, "/home/ubuntu/hr-rag-chatbot/services/rag-pipeline")


def test_invalid_answer_reason_detects_empty_and_title_only_answers():
    from app.pipeline import _invalid_answer_reason

    assert _invalid_answer_reason("") == "empty_answer"
    assert _invalid_answer_reason("## Only a title") == "title_only_answer"
    assert _invalid_answer_reason("## Title\n\nActual answer body.") is None


def test_should_flush_deep_buffer_waits_for_substantive_body_after_heading():
    from app.pipeline import _should_flush_deep_buffer

    assert _should_flush_deep_buffer("## Title") is False
    assert _should_flush_deep_buffer("## Title\n\nBrief body text.") is True
