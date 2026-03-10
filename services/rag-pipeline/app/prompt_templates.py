"""
============================================================================
FILE: services/rag-pipeline/app/prompt_templates.py
PURPOSE: System prompt and context templates for grounded HR responses.
         Optimized for Qwen3.5-9B with strict document-only grounding.
ARCHITECTURE REF: §8 — Prompt Template
============================================================================
"""

import re
from typing import Any

from app.answer_planner import AnswerPlan
from app.config import settings

SYSTEM_PROMPT = """You are Esyasoft's HR Policy Assistant.

TASK:
Provide a precise, factual answer to the user's question using ONLY the provided Context.

RULES:
1. If the Context does not contain the answer, reply exactly with: "This information is not available in the current HR knowledge base."
2. Extract the facts directly. Do not explain your process, do not use filler words, and do not add preamble.
3. Keep your response brief. Stop writing immediately after answering the core question.

FORMAT:
- Use bullet points for lists.
- Use bold text for key terms.

Context:
{context}
"""

CONTEXT_TEMPLATE = """--- Document: {filename} | Section: {section} | Page: {page_number} ---
{chunk_text}"""

_STOPWORDS = {
    "a", "an", "the", "is", "are", "to", "in", "of", "for", "and", "or",
    "on", "with", "what", "which", "how", "when", "where", "who", "why",
    "does", "do", "can", "should", "would", "from", "this", "that", "about",
}


def _extract_query_terms(query: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9$%]+", (query or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _truncate_chunk_text(text: str, query_terms: set[str]) -> str:
    """
    Prepare chunk text for the LLM prompt.

    Sends as much of the chunk as possible within the configured character limit.
    No aggressive sentence filtering — the retriever and reranker already selected
    the most relevant chunks. Truncation should be a last resort, not the default.
    """
    if not text:
        return ""

    # Normalize whitespace
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""

    # Use the configured char limit (default 1200, configurable via PROMPT_MAX_CHUNK_CHARS)
    limit = settings.prompt_max_chunk_chars
    if len(cleaned) <= limit:
        return cleaned

    # Only truncate if exceeding the limit — preserve as much context as possible
    return cleaned[:limit].rstrip() + " ..."


def build_context_string(retrieved_chunks: list[dict[str, Any]], question: str) -> str:
    if not retrieved_chunks:
        return "No relevant documents found in the knowledge base."

    query_terms = _extract_query_terms(question)
    parts: list[str] = []
    for chunk in retrieved_chunks:
        chunk_text = _truncate_chunk_text(chunk.get("text", ""), query_terms)
        if chunk_text:
            parts.append(CONTEXT_TEMPLATE.format(
                filename=chunk.get("filename", "Unknown"),
                section=chunk.get("section", "Unknown Section"),
                page_number=chunk.get("page_number", "?"),
                chunk_text=chunk_text,
            ))

    return "\n\n".join(parts)


def build_prompt(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    answer_plan: AnswerPlan | None = None,
) -> str:
    context = build_context_string(retrieved_chunks, question)
    return SYSTEM_PROMPT.format(context=context)


def format_as_chat(
    system_prompt: str,
    question: str,
    conversation_history: list | None = None,
) -> list[dict[str, str]]:
    """Format messages for the LLM chat API (OpenAI-compatible format)."""
    messages = [{"role": "system", "content": system_prompt}]

    valid_history = []
    if conversation_history:
        expected_role = "assistant"
        for turn in reversed(conversation_history):
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role == expected_role and content:
                if role == "assistant" and len(content) > 200:
                    content = content[:200] + "..."
                valid_history.insert(0, {"role": role, "content": content})
                expected_role = "user" if role == "assistant" else "assistant"
                
            if len(valid_history) >= 6 and expected_role == "assistant":
                break
                
        if expected_role == "user" and valid_history:
            valid_history.pop(0)

        messages.extend(valid_history)

    messages.append({"role": "user", "content": question})
    return messages


# Backward-compatible alias
format_as_mistral_chat = format_as_chat
