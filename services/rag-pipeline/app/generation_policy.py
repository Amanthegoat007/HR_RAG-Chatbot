from dataclasses import dataclass
import re
from typing import Literal, Optional

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
    reasoning_mode: str
    profile: str
    max_tokens: int
    stop: list[str]
    temperature: float


def choose_generation_policy(
    query: str,
    question_type: str = "fact",
    user_role: str = "employee",
    requested_reasoning_mode: Optional[Literal["fast", "deep"]] = None,
    answer_path: str = "llm",
) -> GenerationPolicy:
    """
    Choose reasoning depth and response budget from query complexity.
    """
    normalized = " ".join((query or "").lower().split())
    word_count = len(re.findall(r"\w+", normalized))
    reasoning_mode = _choose_reasoning_mode(
        requested_reasoning_mode=requested_reasoning_mode,
        answer_path=answer_path,
    )

    profile = "short"
    max_tokens = (
        settings.llm_max_tokens_deep_short
        if reasoning_mode == "deep"
        else settings.llm_max_tokens_short
    )

    if reasoning_mode == "deep" and (
        question_type in {"calc", "compare", "explain"}
        or word_count >= 18
        or any(hint in normalized for hint in _LONG_HINTS)
    ):
        profile = "long"
        max_tokens = settings.llm_max_tokens_deep_long
    elif (
        question_type in {"list", "calc", "compare", "eligibility"}
        or word_count >= 10
        or any(hint in normalized for hint in _MEDIUM_HINTS)
    ):
        profile = "medium"
        max_tokens = (
            settings.llm_max_tokens_deep_medium
            if reasoning_mode == "deep"
            else settings.llm_max_tokens_medium
        )
    elif reasoning_mode == "deep":
        max_tokens = settings.llm_max_tokens_deep_short

    max_cap = (
        settings.llm_max_tokens_deep_cap
        if reasoning_mode == "deep"
        else settings.llm_max_tokens
    )
    bounded = max(48, min(int(max_tokens), int(max_cap)))
    stop = [settings.llm_stop_sequence] if settings.llm_stop_sequence else []

    if user_role == "employee":
        temperature = 0.28 if reasoning_mode == "deep" else 0.38
    else:
        temperature = 0.08 if reasoning_mode == "deep" else 0.12

    return GenerationPolicy(
        reasoning_mode=reasoning_mode,
        profile=profile,
        max_tokens=bounded,
        stop=stop,
        temperature=temperature,
    )


def _choose_reasoning_mode(
    requested_reasoning_mode: Optional[Literal["fast", "deep"]],
    answer_path: str,
) -> str:
    if answer_path == "deterministic":
        return "fast"

    if requested_reasoning_mode == "deep":
        return "deep"

    return "fast"
