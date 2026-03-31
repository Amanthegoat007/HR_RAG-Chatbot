import os
import sys

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
