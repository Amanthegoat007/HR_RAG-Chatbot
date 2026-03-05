from dataclasses import dataclass
import re

from app.config import settings


_MEDIUM_HINTS = (
    "list",
    "program",
    "benefit",
    "eligibility",
    "criteria",
    "requirement",
    "policy",
    "compare",
)

_LONG_HINTS = (
    "summarize",
    "summary",
    "detailed",
    "detail",
    "explain",
    "process",
    "procedure",
    "step",
    "all",
    "comprehensive",
)


@dataclass(frozen=True)
class GenerationPolicy:
    profile: str
    max_tokens: int
    stop: list[str]


def choose_generation_policy(query: str) -> GenerationPolicy:
    """
    Choose response token budget from query complexity.
    This cuts decode latency without changing retrieval/rerank quality.
    """
    normalized = " ".join((query or "").lower().split())
    word_count = len(re.findall(r"\w+", normalized))

    profile = "short"
    max_tokens = settings.llm_max_tokens_short

    if word_count >= 18 or any(hint in normalized for hint in _LONG_HINTS):
        profile = "long"
        max_tokens = settings.llm_max_tokens_long
    elif word_count >= 10 or any(hint in normalized for hint in _MEDIUM_HINTS):
        profile = "medium"
        max_tokens = settings.llm_max_tokens_medium

    bounded = max(48, min(int(max_tokens), int(settings.llm_max_tokens)))
    stop = [settings.llm_stop_sequence] if settings.llm_stop_sequence else []
    return GenerationPolicy(profile=profile, max_tokens=bounded, stop=stop)
