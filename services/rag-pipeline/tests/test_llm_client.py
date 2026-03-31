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


def test_build_local_chat_payload_disables_thinking_at_top_level():
    from app.llm_client import _build_local_chat_payload

    payload = _build_local_chat_payload(
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=42,
        stop=["<END_ANSWER>"],
        temperature=0.2,
    )

    assert payload["max_tokens"] == 42
    assert payload["temperature"] == 0.2
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["skip_special_tokens"] is True
    assert payload["stop"] == ["<END_ANSWER>", "<|im_end|>", "<|endoftext|>"]
    assert "extra_body" not in payload


def test_build_local_chat_payload_enables_thinking_when_requested():
    from app.llm_client import _build_local_chat_payload

    payload = _build_local_chat_payload(
        messages=[{"role": "user", "content": "Analyze this policy edge case"}],
        enable_thinking=True,
    )

    assert payload["chat_template_kwargs"] == {"enable_thinking": True}


def test_parse_stream_payload_tracks_visible_and_reasoning_content():
    from app.llm_client import _parse_stream_payload

    chunk = _parse_stream_payload(
        '{"choices":[{"delta":{"reasoning_content":"Considering policy branches.","content":"Final answer."}}]}'
    )

    assert chunk is not None
    assert chunk.reasoning_content == "Considering policy branches."
    assert chunk.content == "Final answer."


def test_parse_stream_payload_accepts_openai_content_arrays():
    from app.llm_client import _parse_stream_payload

    chunk = _parse_stream_payload(
        '{"choices":[{"delta":{"content":[{"type":"output_text","text":"Hello"},{"type":"output_text","text":" world"}]}}]}'
    )

    assert chunk is not None
    assert chunk.content == "Hello world"
    assert chunk.reasoning_content == ""
