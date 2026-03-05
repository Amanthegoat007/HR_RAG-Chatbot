"""
============================================================================
FILE: services/query/app/prompt_templates.py
PURPOSE: System prompt and context templates for the Mistral-7B LLM.
         Designed for factual, cited, bilingual HR knowledge responses.
ARCHITECTURE REF: §8 — Prompt Template
============================================================================
"""

import re

from app.config import settings

# ---------------------------------------------------------------------------
# SYSTEM PROMPT (English-only, quality-focused, markdown-formatted)
# ---------------------------------------------------------------------------
# Design rationale:
# - "ONLY based on provided context" prevents hallucination of HR policies
# - Inline citation format "(Source: filename, Page X)" is parsed by frontend
#   and rendered as styled citation chips
# - Markdown formatting rules ensure beautiful rendering in chat UI
# - Conservative temperature (0.1) set in config ensures deterministic answers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an HR Knowledge Assistant. Use ONLY the provided context.

Return output in this markdown schema:
### Answer
<one direct answer sentence>

1. <optional item>
2. <optional item>

(Source: filename | Section: section | Page: page)
<END_ANSWER>

Rules:
1. Return valid markdown only.
2. Keep it concise and factual.
3. Use a numbered list only when multiple points are needed.
4. Use bold only for key values and policy names.
5. Never invent facts outside context.
6. If missing, return exactly:
   "This information is not available in the current HR knowledge base."
7. End with exactly one citation line and then <END_ANSWER>.

Context:
{context}
"""

# ---------------------------------------------------------------------------
# CONTEXT TEMPLATE
# ---------------------------------------------------------------------------
# Each retrieved chunk is formatted with this template before being included
# in the system prompt. The source attribution enables verifiable citations.
# ---------------------------------------------------------------------------

CONTEXT_TEMPLATE = """[Source: {filename} | Section: {section} | Page: {page_number}]
{chunk_text}"""


_STOPWORDS = {
    "a", "an", "the", "is", "are", "to", "in", "of", "for", "and", "or",
    "on", "with", "what", "which", "how", "when", "where", "who", "why",
    "does", "do", "can", "should", "would", "from", "this", "that", "about",
}


def _extract_query_terms(query: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9$%]+", (query or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _truncate_chunk_text(text: str, query_terms: set[str]) -> str:
    """
    Keep prompt context compact for faster first-token latency.
    """
    if not text:
        return ""

    cleaned = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return ""

    max_sentences = max(1, min(settings.prompt_max_chunk_sentences, 4))

    if not query_terms:
        selected = sentences[:max_sentences]
    else:
        scored: list[tuple[int, int, str]] = []
        for i, sentence in enumerate(sentences):
            lowered = sentence.lower()
            score = sum(1 for term in query_terms if term in lowered)
            scored.append((score, i, sentence))

        scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        top = sorted(scored[:max_sentences], key=lambda row: row[1])
        selected = [row[2] for row in top]

    compact = " ".join(selected).strip()
    if not compact:
        compact = cleaned

    limit = max(180, min(settings.prompt_max_chunk_chars, 450))
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + " ..."



def build_context_string(retrieved_chunks: list[dict], question: str) -> str:
    """
    Build the context string from a list of retrieved and reranked chunks.

    Each chunk is formatted using CONTEXT_TEMPLATE, then joined.
    This becomes the {context} placeholder in SYSTEM_PROMPT.

    Args:
        retrieved_chunks: List of dicts from Qdrant search + reranker, each containing:
            - filename: str
            - section: str
            - page_number: int
            - text: str

    Returns:
        Formatted context string for injection into SYSTEM_PROMPT.
    """
    if not retrieved_chunks:
        return "No relevant documents found in the knowledge base."

    query_terms = _extract_query_terms(question)

    parts = []
    max_chunks = max(1, min(settings.prompt_max_chunks, 2))
    for chunk in retrieved_chunks[:max_chunks]:
        parts.append(CONTEXT_TEMPLATE.format(
            filename=chunk.get("filename", "Unknown"),
            section=chunk.get("section", "Unknown Section"),
            page_number=chunk.get("page_number", "?"),
            chunk_text=_truncate_chunk_text(chunk.get("text", ""), query_terms),
        ))

    return "\n".join(parts)


def build_prompt(question: str, retrieved_chunks: list[dict]) -> str:
    """
    Build the complete prompt by injecting context into the system prompt.

    This is the final prompt sent to the Mistral-7B LLM.

    Args:
        question: The user's question.
        retrieved_chunks: Top-5 reranked chunks from the RAG pipeline.

    Returns:
        Complete prompt string for the LLM API.
    """
    context = build_context_string(retrieved_chunks, question)
    return SYSTEM_PROMPT.format(context=context)


def format_as_mistral_chat(system_prompt: str, question: str) -> list[dict]:
    """
    Format the prompt as a chat message list for llama.cpp OpenAI-compatible API.

    Mistral uses the standard OpenAI chat format:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

    Args:
        system_prompt: The full system prompt with context injected.
        question: The user's question.

    Returns:
        Messages list for the /v1/chat/completions API.
    """
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
