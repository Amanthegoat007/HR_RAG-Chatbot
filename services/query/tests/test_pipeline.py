"""
============================================================================
FILE: services/query/tests/test_pipeline.py
PURPOSE: Unit tests for query-svc — pipeline logic, cache, SSE formatting.
ARCHITECTURE REF: §12 — Testing & Validation
DEPENDENCIES: pytest, unittest.mock
============================================================================
"""

import json
import sys
import os

import pytest

# Set required environment variables before importing any app modules
os.environ.setdefault("JWT_SECRET", "test_secret_key_at_least_256_bits_long_for_testing")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("QDRANT_PORT", "6333")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("EMBEDDING_SVC_URL", "http://localhost:8004")
os.environ.setdefault("RERANKER_SVC_URL", "http://localhost:8005")
os.environ.setdefault("LLM_SERVER_URL", "http://localhost:8080")
os.environ.setdefault("QDRANT_COLLECTION", "hr_documents")

sys.path.insert(0, "/app")


# ──────────────────────────────────────────────────────────────────────────────
# Cache Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestSemanticCacheLogic:
    """Tests for cache normalization and similarity logic (no Redis required)."""

    def test_normalize_vector_unit_length(self):
        """Normalized vector should have L2 norm = 1.0."""
        import math
        from app.cache import SemanticCache

        cache = SemanticCache.__new__(SemanticCache)  # Don't call __init__
        vec = [3.0, 4.0]  # L2 norm = 5
        normalized = cache._normalize(vec)
        l2_norm = math.sqrt(sum(v ** 2 for v in normalized))
        assert abs(l2_norm - 1.0) < 1e-6, f"Expected norm=1.0, got {l2_norm}"

    def test_normalize_zero_vector_returns_zeros(self):
        """Zero vector should return all zeros (avoid division by zero)."""
        from app.cache import SemanticCache

        cache = SemanticCache.__new__(SemanticCache)
        vec = [0.0, 0.0, 0.0]
        normalized = cache._normalize(vec)
        assert all(v == 0.0 for v in normalized), "Zero vector should stay zero"

    def test_cosine_similarity_identical_vectors(self):
        """Cosine similarity of a vector with itself should be 1.0."""
        from app.cache import SemanticCache

        cache = SemanticCache.__new__(SemanticCache)
        vec = [0.6, 0.8]  # Already unit length (3-4-5 triangle normalized)
        # Normalize first (as cache does)
        n = cache._normalize(vec)
        sim = cache._cosine_similarity(n, n)
        assert abs(sim - 1.0) < 1e-6, f"Expected 1.0, got {sim}"

    def test_cosine_similarity_orthogonal_vectors(self):
        """Orthogonal vectors should have cosine similarity = 0."""
        from app.cache import SemanticCache

        cache = SemanticCache.__new__(SemanticCache)
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        sim = cache._cosine_similarity(v1, v2)
        assert abs(sim) < 1e-6, f"Expected 0.0, got {sim}"

    def test_cosine_similarity_opposite_vectors(self):
        """Opposite vectors should have cosine similarity = -1."""
        from app.cache import SemanticCache

        cache = SemanticCache.__new__(SemanticCache)
        v1 = [1.0, 0.0]
        v2 = [-1.0, 0.0]
        sim = cache._cosine_similarity(v1, v2)
        assert abs(sim - (-1.0)) < 1e-6, f"Expected -1.0, got {sim}"


# ──────────────────────────────────────────────────────────────────────────────
# SSE Handler Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestSSEHandler:
    """Tests for SSE event building functions."""

    def test_token_event_structure(self):
        """Token event should have correct event type and JSON payload."""
        from app.sse_handler import make_token_event

        event = make_token_event("Hello")
        assert event.event == "token"
        data = json.loads(event.data)
        assert data["token"] == "Hello"

    def test_token_event_unicode(self):
        """Token event should handle Arabic text without encoding issues."""
        from app.sse_handler import make_token_event

        arabic_token = "الإجازة"
        event = make_token_event(arabic_token)
        data = json.loads(event.data)
        assert data["token"] == arabic_token

    def test_sources_event_structure(self):
        """Sources event should include all required citation fields."""
        from app.sse_handler import make_sources_event

        chunks = [{
            "filename": "leave_policy.pdf",
            "section": "Annual Leave",
            "page_number": 3,
            "document_id": "abc-123",
            "chunk_index": 5,
            "rerank_score": 0.92,
            "heading_path": "Policy > §2 Leave",
        }]
        event = make_sources_event(chunks)
        assert event.event == "sources"
        data = json.loads(event.data)
        assert len(data["sources"]) == 1
        source = data["sources"][0]
        assert source["filename"] == "leave_policy.pdf"
        assert source["page_number"] == 3
        assert source["heading_path"] == "Policy > §2 Leave"

    def test_sources_event_empty(self):
        """Sources event with empty list should produce empty sources array."""
        from app.sse_handler import make_sources_event

        event = make_sources_event([])
        data = json.loads(event.data)
        assert data["sources"] == []

    def test_error_event_structure(self):
        """Error event should include message and code fields."""
        from app.sse_handler import make_error_event

        event = make_error_event("Service unavailable", code="llm_error")
        assert event.event == "error"
        data = json.loads(event.data)
        assert data["error"] == "Service unavailable"
        assert data["code"] == "llm_error"

    def test_done_event_structure(self):
        """Done event should signal stream completion."""
        from app.sse_handler import make_done_event

        event = make_done_event()
        assert event.event == "done"
        data = json.loads(event.data)
        assert data["status"] == "complete"

    @pytest.mark.asyncio
    async def test_build_query_stream_yields_tokens_then_sources(self):
        """build_query_stream should yield token events then a sources event."""
        from app.sse_handler import build_query_stream

        async def mock_tokens():
            for word in ["Hello", " ", "world"]:
                yield word

        source_chunks = [{"filename": "test.pdf", "section": "S1", "page_number": 1,
                          "document_id": "d1", "chunk_index": 0, "rerank_score": 0.9}]

        events = []
        async for event in build_query_stream(mock_tokens(), source_chunks):
            events.append(event)

        # Should be: 3 tokens + 1 sources + 1 done
        assert len(events) == 5
        event_types = [e.event for e in events]
        assert event_types == ["token", "token", "token", "sources", "done"]

    @pytest.mark.asyncio
    async def test_build_query_stream_handles_generator_error(self):
        """build_query_stream should emit error event if token generator fails."""
        from app.sse_handler import build_query_stream

        async def failing_tokens():
            yield "Hello"
            raise RuntimeError("LLM connection dropped")

        events = []
        async for event in build_query_stream(failing_tokens(), []):
            events.append(event)

        event_types = [e.event for e in events]
        assert "error" in event_types
        assert "done" in event_types


# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestCircuitBreaker:
    """Tests for the LLM circuit breaker logic."""

    def test_initially_closed(self):
        """Circuit should start in CLOSED state."""
        from app.llm_client import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available is True

    def test_opens_after_threshold_failures(self):
        """Circuit should open after 3 consecutive failures."""
        from app.llm_client import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # Not open yet
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_available is False

    def test_success_resets_to_closed(self):
        """Successful call should reset circuit to CLOSED."""
        from app.llm_client import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_transitions_to_half_open_after_timeout(self):
        """Circuit should become HALF_OPEN after recovery timeout."""
        import time
        from unittest.mock import patch
        from app.llm_client import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

        # Simulate time passing by patching monotonic
        future_time = time.monotonic() + 2.0
        with patch("app.llm_client.time.monotonic", return_value=future_time):
            # The state property auto-transitions to HALF_OPEN
            # We need to access _circuit_breaker's state, but here we test the CB directly
            # Patch the CB's internal _last_failure_time
            cb._last_failure_time = time.monotonic() - 2.0
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_available is True


# ──────────────────────────────────────────────────────────────────────────────
# Prompt Template Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestPromptTemplates:
    """Tests for LLM prompt construction."""

    def test_system_prompt_exists(self):
        """SYSTEM_PROMPT should be defined and non-empty."""
        from app.prompt_templates import SYSTEM_PROMPT

        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 50, "SYSTEM_PROMPT seems too short"

    def test_build_user_message_includes_query(self):
        """build_user_message should include the original query text."""
        from app.prompt_templates import build_user_message

        chunks = [{"text": "Annual leave is 30 days per year.", "filename": "policy.pdf",
                   "section": "Leave", "page_number": 1}]
        message = build_user_message("How many days leave do I get?", chunks)
        assert "How many days leave do I get?" in message

    def test_build_user_message_includes_chunk_text(self):
        """build_user_message should include text from all chunks."""
        from app.prompt_templates import build_user_message

        chunks = [
            {"text": "Chunk A content here.", "filename": "policy.pdf", "section": "S1", "page_number": 1},
            {"text": "Chunk B content here.", "filename": "policy.pdf", "section": "S2", "page_number": 2},
        ]
        message = build_user_message("test query", chunks)
        assert "Chunk A content here." in message
        assert "Chunk B content here." in message

    def test_build_user_message_no_chunks(self):
        """build_user_message should handle empty chunk list gracefully."""
        from app.prompt_templates import build_user_message

        message = build_user_message("test query", [])
        assert isinstance(message, str)
        assert len(message) > 0

    def test_build_user_message_includes_source_citation(self):
        """build_user_message should cite filename and page number."""
        from app.prompt_templates import build_user_message

        chunks = [{"text": "Test content.", "filename": "HR_Policy.pdf",
                   "section": "§3", "page_number": 7}]
        message = build_user_message("test", chunks)
        assert "HR_Policy.pdf" in message or "page 7" in message.lower() or "7" in message
