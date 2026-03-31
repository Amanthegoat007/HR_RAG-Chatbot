import asyncio
import json
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


class DummyResolutionCache:
    def __init__(self, cached=None):
        self.cached = cached
        self.saved = None

    async def get(self, **kwargs):
        return self.cached

    async def set(self, **kwargs):
        self.saved = kwargs


def test_llm_first_resolver_returns_direct_for_clear_query(monkeypatch):
    from app import context_resolver

    async def fake_generate_text(**kwargs):
        return json.dumps(
            {
                "resolution_mode": "direct",
                "standalone_query": "Paid Time Off policy",
                "confidence": 0.97,
                "active_subject": "Paid Time Off policy",
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": [],
                "clarification_question": None,
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)
    cache = DummyResolutionCache()

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "PTO policy?",
            [],
            http_client=None,
            cache=cache,
            conversation_id="conv-1",
            session_scope_active=False,
        )
    )

    assert resolution.resolution_mode == "direct"
    assert resolution.standalone_query == "Paid Time Off policy"
    assert resolution.source == "llm"
    assert cache.saved is not None


def test_llm_first_resolver_uses_cache_before_calling_llm(monkeypatch):
    from app import context_resolver

    async def should_not_run(**kwargs):
        raise AssertionError("LLM should not be called on a resolution cache hit")

    monkeypatch.setattr(context_resolver, "generate_text", should_not_run)
    cache = DummyResolutionCache(
        cached={
            "resolution_mode": "resolved_follow_up",
            "standalone_query": "Can the probation period be extended under the probation policy?",
            "confidence": 0.94,
            "active_subject": "Probation policy",
            "latest_topic_reference": "Probation policy",
            "recent_answer_summary": "Probation lasts 6 months and can be extended once with approval.",
            "unresolved_references": ["it"],
            "clarification_question": None,
        }
    )

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "Can it be extended?",
            [
                {
                    "role": "assistant",
                    "content": "## Probation policy\n\nProbation lasts 6 months and can be extended once with approval.",
                    "metadata": {
                        "turnContext": {
                            "activeSubject": "Probation policy",
                            "recentSummary": "Probation lasts 6 months and can be extended once with approval.",
                        }
                    },
                }
            ],
            http_client=None,
            cache=cache,
            conversation_id="conv-2",
            session_scope_active=False,
        )
    )

    assert resolution.source == "cache"
    assert resolution.resolution_mode == "resolved_follow_up"
    assert "probation policy" in resolution.standalone_query.lower()


def test_llm_first_resolver_retries_invalid_json_once(monkeypatch):
    from app import context_resolver

    calls = {"count": 0}

    async def fake_generate_text(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return "not valid json"
        return json.dumps(
            {
                "resolution_mode": "clarify",
                "standalone_query": "",
                "confidence": 0.2,
                "active_subject": "Annual leave",
                "latest_topic_reference": None,
                "recent_answer_summary": "I summarized annual leave only.",
                "unresolved_references": ["that"],
                "clarification_question": "Do you want annual leave, sick leave, or another leave policy?",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "What about that?",
            [
                {
                    "role": "assistant",
                    "content": "## Annual leave\n\nI summarized annual leave only.",
                    "metadata": {
                        "turnContext": {
                            "activeSubject": "Annual leave",
                            "recentSummary": "I summarized annual leave only.",
                        }
                    },
                }
            ],
            http_client=None,
            cache=None,
            conversation_id="conv-3",
            session_scope_active=False,
        )
    )

    assert calls["count"] == 2
    assert resolution.resolution_mode == "clarify"
    assert resolution.clarification_question is not None


def test_llm_first_resolver_falls_back_safely_on_llm_failure(monkeypatch):
    from app import context_resolver

    async def failing_generate_text(**kwargs):
        raise RuntimeError("resolver unavailable")

    monkeypatch.setattr(context_resolver, "generate_text", failing_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "Can it be extended?",
            [
                {
                    "role": "assistant",
                    "content": "## Probation policy\n\nProbation lasts 6 months and can be extended once with approval.",
                    "metadata": {
                        "turnContext": {
                            "activeSubject": "Probation policy",
                            "recentSummary": "Probation lasts 6 months and can be extended once with approval.",
                        }
                    },
                }
            ],
            http_client=None,
            cache=None,
            conversation_id="conv-4",
            session_scope_active=True,
        )
    )

    assert resolution.source == "fallback"
    assert resolution.resolution_mode == "resolved_follow_up"
    assert "probation policy" in resolution.standalone_query.lower()
