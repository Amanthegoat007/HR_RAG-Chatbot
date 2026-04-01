import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test_secret_at_least_256bits_long_for_testing")
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "minioadmin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "$2b$12$testhashtesthashhh")
os.environ.setdefault("USER_PASSWORD_HASH", "$2b$12$testhashhh")

sys.path.insert(0, "/home/ubuntu/hr-rag-chatbot/services/backend")


def test_normalize_markdown_answer_strips_qwen_reasoning_artifacts():
    from app.services.response_formatter import normalize_markdown_answer

    raw = ".cw\n</think>\n\n* No, both spouses cannot keep individual benefits."

    assert normalize_markdown_answer(raw) == "* No, both spouses cannot keep individual benefits."


def test_normalize_markdown_answer_strips_full_think_block():
    from app.services.response_formatter import normalize_markdown_answer

    raw = "<think>internal reasoning</think>\n\nAnswer"

    assert normalize_markdown_answer(raw) == "Answer"


def test_build_assistant_message_metadata_creates_structured_payload():
    from app.services.assistant_response_builder import build_assistant_message_metadata

    answer = """## End-of-Service Comparison

No, the end-of-service calculation is not the same for UAE nationals and expatriates.

- **UAE Nationals:** Covered under the pension scheme.
- **Expatriates:** Receive end-of-service benefit under the policy.
"""

    metadata = build_assistant_message_metadata(
        question="Is end-of-service calculated the same way for UAE nationals and expats?",
        answer_text=answer,
        sources=[{"filename": "policy.pdf", "section": "Benefits", "page_number": 7}],
        upstream_meta={"question_type": "compare", "reasoning_mode": "deep"},
    )

    payload = metadata["responsePayload"]
    assert metadata["reasoningMode"] == "deep"
    assert payload["questionType"] == "compare"
    assert payload["blocks"][0] == {"type": "title", "content": "End-of-Service Comparison"}
    assert payload["blocks"][1]["type"] == "summary"
    assert payload["blocks"][2]["type"] == "comparison"
    assert payload["sources"][0]["filename"] == "policy.pdf"


def test_build_assistant_message_metadata_omits_title_only_structured_payload():
    from app.services.assistant_response_builder import build_assistant_message_metadata

    metadata = build_assistant_message_metadata(
        question="What is Esyasoft's corporate vision?",
        answer_text="## Esyasoft's corporate vision",
        sources=[],
        upstream_meta={"question_type": "fact", "reasoning_mode": "fast"},
    )

    assert "responsePayload" not in metadata
    assert metadata["questionType"] == "fact"


def test_build_assistant_message_metadata_includes_context_resolution():
    from app.services.assistant_response_builder import build_assistant_message_metadata

    metadata = build_assistant_message_metadata(
        question="Can it be extended?",
        answer_text="## Probation\n\nYes, it can be extended once with approval.",
        sources=[],
        upstream_meta={
            "question_type": "fact",
            "reasoning_mode": "fast",
            "context_resolution": {
                "resolution_mode": "resolved_follow_up",
                "standalone_query": "Can the probation period be extended under the probation policy?",
                "confidence": 0.93,
                "active_subject": "Probation policy",
                "latest_topic_reference": "Probation policy",
                "recent_answer_summary": "Probation lasts 6 months and can be extended once with approval.",
                "unresolved_references": ["it"],
                "clarification_question": None,
                "source": "llm",
            },
        },
    )

    assert metadata["contextResolution"]["resolutionMode"] == "resolved_follow_up"
    assert metadata["contextResolution"]["source"] == "llm"


def test_build_trust_summary_uses_document_metadata_and_detects_conflicts():
    from app.services.assistant_enrichment import build_trust_summary

    now = datetime.now(timezone.utc)
    sources = [
        {
            "filename": "Leave_Policy_v4.pdf",
            "section": "Annual Leave",
            "page_number": 3,
            "document_id": "doc-1",
            "score": 0.91,
        },
        {
            "filename": "Leave_Policy_v5.pdf",
            "section": "Annual Leave",
            "page_number": 4,
            "document_id": "doc-2",
            "score": 0.82,
        },
    ]
    document_records = {
        "doc-1": {
            "filename": "Leave_Policy_v4.pdf",
            "uploaded_at": now - timedelta(days=12),
            "processed_at": now - timedelta(days=10),
            "metadata": {
                "policy_title": "Leave Policy",
                "policy_family": "Leave Policy",
                "policy_version": "v4.0",
                "effective_date": "2026-01-01",
                "owner": "HR Operations",
            },
        },
        "doc-2": {
            "filename": "Leave_Policy_v5.pdf",
            "uploaded_at": now - timedelta(days=9),
            "processed_at": now - timedelta(days=8),
            "metadata": {
                "policy_title": "Leave Policy",
                "policy_family": "Leave Policy",
                "policy_version": "v5.0",
                "effective_date": "2026-02-01",
                "owner": "HR Operations",
            },
        },
    }

    summary = build_trust_summary(sources, document_records=document_records)

    assert summary["policyTitle"] == "Leave Policy"
    assert summary["policyVersion"] == "v4.0"
    assert summary["effectiveDateLabel"] == "Jan 01, 2026"
    assert summary["owner"] == "HR Operations"
    assert summary["groundingLabel"] == "High grounding"
    assert summary["hasConflict"] is True
    assert "conflict" in summary["conflictLabel"].lower() or "mismatch" in summary["conflictLabel"].lower()


def test_build_related_suggestions_are_grounded_sparse_and_role_aware():
    from app.services.assistant_enrichment import build_related_suggestions

    metadata = {
        "answerPath": "llm",
        "contextResolution": {
            "activeSubject": "Public Holiday Policy",
        },
    }
    sources = [
        {
            "filename": "Public_Holiday_Policy.pdf",
            "section": "Public Holidays",
            "page_number": 2,
            "document_id": "doc-1",
            "score": 0.88,
        }
    ]
    trust_summary = {
        "policyTitle": "Public Holiday Policy",
        "policyFamily": "Public Holiday Policy",
    }

    manager_suggestions = build_related_suggestions(
        question="What are the holidays this year?",
        user_role="manager",
        metadata=metadata,
        sources=sources,
        trust_summary=trust_summary,
    )

    assert len(manager_suggestions) == 3
    assert manager_suggestions[0]["label"] == "Holiday overlap"
    assert any("manager" in suggestion["prompt"].lower() for suggestion in manager_suggestions)

    no_context_suggestions = build_related_suggestions(
        question="What are the holidays this year?",
        user_role="employee",
        metadata={"answerPath": "no_context"},
        sources=sources,
        trust_summary=trust_summary,
    )
    assert no_context_suggestions == []
