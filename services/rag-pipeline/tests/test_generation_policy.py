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


def test_choose_generation_policy_uses_fast_for_simple_fact():
    from app.generation_policy import choose_generation_policy

    policy = choose_generation_policy(
        query="What is the probation period?",
        question_type="fact",
    )

    assert policy.reasoning_mode == "fast"


def test_choose_generation_policy_uses_deep_when_explicitly_requested():
    from app.generation_policy import choose_generation_policy

    policy = choose_generation_policy(
        query="Can I claim the allowance if my spouse also works here?",
        question_type="eligibility",
        requested_reasoning_mode="deep",
    )

    assert policy.reasoning_mode == "deep"
    assert policy.profile in {"medium", "long"}


def test_choose_generation_policy_defaults_to_fast_for_direct_eligibility_question():
    from app.generation_policy import choose_generation_policy

    policy = choose_generation_policy(
        query="Can both spouses claim individual medical benefits and air ticket allowances?",
        question_type="eligibility",
    )

    assert policy.reasoning_mode == "fast"


def test_choose_generation_policy_keeps_rewritten_fact_query_fast_without_override():
    from app.generation_policy import choose_generation_policy

    policy = choose_generation_policy(
        query="What is Esyasoft's corporate vision?",
        question_type="fact",
        requested_reasoning_mode=None,
    )

    assert policy.reasoning_mode == "fast"


def test_classify_question_treats_dual_claim_question_as_eligibility_not_compare():
    from app.answer_planner import classify_question

    question_type = classify_question(
        "Can both spouses claim individual medical benefits and air ticket allowances?"
    )

    assert question_type == "eligibility"
