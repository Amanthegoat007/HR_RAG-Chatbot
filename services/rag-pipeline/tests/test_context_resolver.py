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
                "focus_type": "policy",
                "focus_id": None,
                "focus_label": "Paid Time Off policy",
                "action": "retrieve",
                "interaction_type": "knowledge_request",
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
            "focus_type": "policy",
            "focus_id": None,
            "focus_label": "Probation policy",
            "action": "retrieve",
            "interaction_type": "knowledge_request",
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
                "focus_type": "none",
                "focus_id": None,
                "focus_label": None,
                "action": "clarify",
                "interaction_type": "clarify",
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


def test_document_reference_resolves_to_single_ready_session_document(monkeypatch):
    from app import context_resolver

    async def fake_generate_text(**kwargs):
        return json.dumps(
            {
                "resolution_mode": "clarify",
                "standalone_query": "",
                "confidence": 0.2,
                "active_subject": None,
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": ["this"],
                "clarification_question": "Which document do you mean?",
                "focus_type": "none",
                "focus_id": None,
                "focus_label": None,
                "action": "clarify",
                "interaction_type": "clarify",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "Can you explain this uploaded document?",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-doc-1",
            session_scope_active=True,
            conversation_working_set={
                "session_documents": [
                    {
                        "document_id": "doc-1",
                        "display_name": "Jane_Doe_Jan_Bill_Annotated.png",
                        "status": "ready",
                    }
                ],
                "latest_ready_document_id": "doc-1",
            },
        )
    )

    assert resolution.action == "retrieve"
    assert resolution.focus_type == "document"
    assert resolution.focus_id == "doc-1"
    assert "uploaded document" in resolution.standalone_query.lower()


def test_document_reference_returns_status_only_for_processing_upload(monkeypatch):
    from app import context_resolver

    async def fake_generate_text(**kwargs):
        return json.dumps(
            {
                "resolution_mode": "clarify",
                "standalone_query": "",
                "confidence": 0.15,
                "active_subject": None,
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": ["document"],
                "clarification_question": "Which file should I use?",
                "focus_type": "none",
                "focus_id": None,
                "focus_label": None,
                "action": "clarify",
                "interaction_type": "clarify",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "Explain the uploaded document in this conversation.",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-doc-2",
            session_scope_active=True,
            conversation_working_set={
                "session_documents": [
                    {
                        "document_id": "doc-2",
                        "display_name": "Offer_Letter.pdf",
                        "status": "processing",
                    }
                ],
                "active_attachment_document_id": "doc-2",
            },
        )
    )

    assert resolution.action == "status_only"
    assert resolution.focus_type == "document"
    assert resolution.focus_id == "doc-2"


def test_greeting_query_routes_through_llm_semantic_router(monkeypatch):
    from app import context_resolver

    calls = {"count": 0}

    async def fake_generate_text(**kwargs):
        calls["count"] += 1
        assert "Latest user query: hello" in kwargs["messages"][-1]["content"]
        return json.dumps(
            {
                "resolution_mode": "direct",
                "standalone_query": "hello",
                "confidence": 0.97,
                "active_subject": "HR copilot",
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": [],
                "clarification_question": None,
                "focus_type": "none",
                "focus_id": None,
                "focus_label": None,
                "action": "direct_response",
                "interaction_type": "greeting",
                "assistant_response_style": "greeting_warm",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "hello",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-greet-1",
            session_scope_active=False,
        )
    )

    assert calls["count"] == 1
    assert resolution.action == "direct_response"
    assert resolution.interaction_type == "greeting"
    assert resolution.assistant_response_style == "greeting_warm"


def test_capability_query_routes_through_llm_semantic_router(monkeypatch):
    from app import context_resolver

    calls = {"count": 0}

    async def fake_generate_text(**kwargs):
        calls["count"] += 1
        assert "ok tell me what you can overall do" in kwargs["messages"][-1]["content"].lower()
        return json.dumps(
            {
                "resolution_mode": "direct",
                "standalone_query": "ok tell me what you can overall do",
                "confidence": 0.95,
                "active_subject": "HR copilot",
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": [],
                "clarification_question": None,
                "focus_type": "none",
                "focus_id": None,
                "focus_label": None,
                "action": "direct_response",
                "interaction_type": "capability",
                "assistant_response_style": "capability_overview",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "ok tell me what you can overall do",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-greet-2",
            session_scope_active=False,
        )
    )

    assert calls["count"] == 1
    assert resolution.action == "direct_response"
    assert resolution.interaction_type == "capability"
    assert resolution.assistant_response_style == "capability_overview"


def test_acknowledgement_query_routes_to_direct_response(monkeypatch):
    from app import context_resolver

    async def fake_generate_text(**kwargs):
        assert "Latest user query: that's good" in kwargs["messages"][-1]["content"]
        return json.dumps(
            {
                "resolution_mode": "direct",
                "standalone_query": "that's good",
                "confidence": 0.92,
                "active_subject": "HR copilot",
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": [],
                "clarification_question": None,
                "focus_type": "none",
                "focus_id": None,
                "focus_label": None,
                "action": "direct_response",
                "interaction_type": "acknowledgement",
                "assistant_response_style": "acknowledgement_positive",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "that's good",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-greet-ack",
            session_scope_active=False,
        )
    )

    assert resolution.action == "direct_response"
    assert resolution.interaction_type == "acknowledgement"
    assert resolution.assistant_response_style == "acknowledgement_positive"


def test_mixed_greeting_query_is_semantically_routed_to_retrieval(monkeypatch):
    from app import context_resolver

    async def fake_generate_text(**kwargs):
        user_message = kwargs["messages"][-1]["content"]
        assert "Latest user query: hi, explain probation policy" in user_message
        return json.dumps(
            {
                "resolution_mode": "direct",
                "standalone_query": "Explain probation policy",
                "confidence": 0.94,
                "active_subject": "Probation policy",
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": [],
                "clarification_question": None,
                "focus_type": "policy",
                "focus_id": None,
                "focus_label": "Probation policy",
                "action": "retrieve",
                "interaction_type": "knowledge_request",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "hi, explain probation policy",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-greet-3",
            session_scope_active=False,
        )
    )

    assert resolution.action == "retrieve"
    assert resolution.interaction_type == "knowledge_request"
    assert resolution.standalone_query == "Explain probation policy"


def test_generic_document_reference_clarifies_when_multiple_ready_documents_exist(monkeypatch):
    from app import context_resolver

    async def fake_generate_text(**kwargs):
        return json.dumps(
            {
                "resolution_mode": "direct",
                "standalone_query": "Explain this uploaded document",
                "confidence": 0.88,
                "active_subject": None,
                "latest_topic_reference": None,
                "recent_answer_summary": None,
                "unresolved_references": ["this"],
                "clarification_question": None,
                "focus_type": "document",
                "focus_id": None,
                "focus_label": None,
                "action": "retrieve",
                "interaction_type": "document_request",
            }
        )

    monkeypatch.setattr(context_resolver, "generate_text", fake_generate_text)

    resolution = asyncio.run(
        context_resolver.resolve_conversation_context(
            "Explain this uploaded document",
            [],
            http_client=None,
            cache=None,
            conversation_id="conv-doc-3",
            session_scope_active=True,
            conversation_working_set={
                "session_documents": [
                    {
                        "document_id": "doc-1",
                        "display_name": "Offer_Letter.pdf",
                        "status": "ready",
                    },
                    {
                        "document_id": "doc-2",
                        "display_name": "Medical_Benefits.pdf",
                        "status": "ready",
                    },
                ],
                "latest_ready_document_id": "doc-2",
            },
        )
    )

    assert resolution.action == "clarify"
    assert resolution.interaction_type == "clarify"
    assert resolution.clarification_question is not None
    assert "Offer_Letter.pdf" in resolution.clarification_question
    assert "Medical_Benefits.pdf" in resolution.clarification_question
