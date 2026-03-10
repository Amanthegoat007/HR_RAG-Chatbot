import re
from typing import Any


def normalize_markdown_answer(text: str, sources: list[dict[str, Any]] | None = None) -> str:
    """
    Clean up raw LLM output into well-formed markdown.

    This does NOT inject any headers or citations — the system prompt
    already instructs the LLM to answer directly, and source citations
    are sent separately via SSE events.
    """
    cleaned = (text or "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\u00a0", " ")

    # Remove stop tokens the LLM may emit
    cleaned = cleaned.replace("<END_ANSWER>", "")

    # Strip any "### Answer" or "**Answer**" headers the LLM may still produce
    cleaned = re.sub(r"^#{1,4}\s*Answer\s*\n+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\*{1,2}Answer\*{1,2}\s*\n+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Answer[:\s]*\n+", "", cleaned, flags=re.IGNORECASE)

    # Remove inline (Source: ...) citations — sources are shown separately
    cleaned = re.sub(r"\n?\(Source:[^)]+\)\s*", "\n", cleaned)

    # Normalize list formatting
    cleaned = _normalize_lists(cleaned)

    # Clean up whitespace
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned


def _normalize_lists(text: str) -> str:
    """Ensure numbered and bullet lists have proper line breaks."""
    # Split merged numbered items: "sentence. 1. item" or "steps: 1. item"
    text = re.sub(r"([.!?:])\s+(\d+\.\s+)", r"\1\n\n\2", text)
    # Also split "text 1. **item" where there's no punctuation before the number
    text = re.sub(r"([a-z])\s+(\d+\.\s+\*\*)", r"\1\n\n\2", text)
    # Fix "1. — item" dash formatting
    text = re.sub(r"(\d+\.)\s+—\s+", r"\1 ", text)
    # Split merged bullet items
    text = re.sub(r"([^\n])\s+(-\s+\*\*)", r"\1\n\2", text)
    text = re.sub(r"([^\n])\s+(-\s+)", r"\1\n\2", text)
    return text
