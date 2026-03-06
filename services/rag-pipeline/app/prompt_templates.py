"""
============================================================================
FILE: services/rag-pipeline/app/prompt_templates.py
PURPOSE: System prompt and context templates for grounded HR responses.
ARCHITECTURE REF: §8 — Prompt Template
============================================================================
"""

import re
from typing import Any

from app.answer_planner import AnswerPlan
from app.config import settings

SYSTEM_PROMPT = """You are an HR Knowledge Assistant. Use ONLY the provided context and verified evidence.

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
3. Use VERIFIED_EVIDENCE first. If it contains steps or a final answer, do not contradict it.
4. Never omit values or list items that appear in VERIFIED_EVIDENCE.
5. Use a numbered list only when multiple points are needed.
6. Use bold only for key values and policy names.
7. Never invent facts outside context.
8. If missing, return exactly:
   "This information is not available in the current HR knowledge base."
9. End with exactly one citation line and then <END_ANSWER>.

VERIFIED_EVIDENCE:
{verified_evidence}

Context:
{context}
"""

CONTEXT_TEMPLATE = """[Source: {filename} | Section: {section} | Page: {page_number}]
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
    if not text:
        return ""

    cleaned = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]

    if not sentences:
        return ""

    max_sentences = max(1, min(settings.prompt_max_chunk_sentences, 4))

    if not query_terms:
        selected = sentences[:max_sentences]
    else:
        scored: list[tuple[int, int, str]] = []
        for idx, sentence in enumerate(sentences):
            lowered = sentence.lower()
            score = sum(1 for term in query_terms if term in lowered)
            scored.append((score, idx, sentence))

        scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        top = sorted(scored[:max_sentences], key=lambda row: row[1])
        selected = [row[2] for row in top]

    compact = " ".join(selected).strip() or cleaned
    limit = max(180, min(settings.prompt_max_chunk_chars, 450))
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + " ..."


def build_context_string(retrieved_chunks: list[dict[str, Any]], question: str) -> str:
    if not retrieved_chunks:
        return "No relevant documents found in the knowledge base."

    query_terms = _extract_query_terms(question)
    parts: list[str] = []
    for chunk in retrieved_chunks:
        parts.append(CONTEXT_TEMPLATE.format(
            filename=chunk.get("filename", "Unknown"),
            section=chunk.get("section", "Unknown Section"),
            page_number=chunk.get("page_number", "?"),
            chunk_text=_truncate_chunk_text(chunk.get("text", ""), query_terms),
        ))

    return "\n".join(parts)


def build_prompt(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    answer_plan: AnswerPlan | None = None,
) -> str:
    context = build_context_string(retrieved_chunks, question)
    verified_evidence = _build_verified_evidence(answer_plan)
    return SYSTEM_PROMPT.format(
        context=context,
        verified_evidence=verified_evidence,
    )


def format_as_mistral_chat(system_prompt: str, question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]


def _build_verified_evidence(answer_plan: AnswerPlan | None) -> str:
    if not answer_plan:
        return "None."

    lines = [f"Question type: {answer_plan.question_type}"]
    if answer_plan.facts:
        lines.append("Facts:")
        lines.extend(f"- {fact}" for fact in answer_plan.facts[:8])
    if answer_plan.steps:
        lines.append("Steps:")
        lines.extend(f"- {step}" for step in answer_plan.steps[:6])
    if answer_plan.final_answer:
        lines.append(f"Allowed final answer: {answer_plan.final_answer}")
    if answer_plan.citation_chunks:
        primary = answer_plan.citation_chunks[0]
        lines.append(
            "Use citation: "
            f"(Source: {primary.get('filename', 'Unknown')} | "
            f"Section: {primary.get('section', 'Unknown Section') or 'Unknown Section'} | "
            f"Page: {primary.get('page_number', primary.get('page_start', '?'))})"
        )
    return "\n".join(lines)
