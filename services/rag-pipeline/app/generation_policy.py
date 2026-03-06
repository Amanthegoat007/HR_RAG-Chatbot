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
    temperature: float


def choose_generation_policy(query: str, question_type: str = "fact") -> GenerationPolicy:
    """
    Choose response token budget from query complexity and question type.
    """
    normalized = " ".join((query or "").lower().split())
    word_count = len(re.findall(r"\w+", normalized))

    profile = "short"
    max_tokens = settings.llm_max_tokens_short

    if question_type == "explain" or word_count >= 18 or any(hint in normalized for hint in _LONG_HINTS):
        profile = "long"
        max_tokens = settings.llm_max_tokens_long
    elif (
        question_type in {"list", "calc"}
        or word_count >= 10
        or any(hint in normalized for hint in _MEDIUM_HINTS)
    ):
        profile = "medium"
        max_tokens = settings.llm_max_tokens_medium

    bounded = max(48, min(int(max_tokens), int(settings.llm_max_tokens)))
    stop = [settings.llm_stop_sequence] if settings.llm_stop_sequence else []
    temperature = 0.0 if question_type in {"calc", "list"} else settings.llm_temperature
    return GenerationPolicy(
        profile=profile,
        max_tokens=bounded,
        stop=stop,
        temperature=temperature,
    )
