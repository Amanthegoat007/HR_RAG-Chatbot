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

EMPLOYEE_PERSONA = """You are "Esy", Esyasoft's helpful HR Assistant."""

ADMIN_PERSONA = """You are Esyasoft's HR Policy Expert."""

SYSTEM_PROMPT_TEMPLATE = """{persona}

RULES:
1. Answer ONLY from the Context Documents below. If the answer is not there, say: "This information is not available in the current HR knowledge base."
2. NEVER guess, infer, or hallucinate information.
3. Be concise and direct. NO filler phrases like "Hello", "Based on the policy", "Sure", "Great question".
4. Format every answer using this structure:
   - Line 1: Markdown heading starting with ## and a short descriptive title.
   - Line 2+: A short summary paragraph that answers the question directly.
   - Then a compact list of key points.
5. For calculations, use numbered steps after the summary.
6. For comparisons, keep the summary first and then use bullets that start with the comparison label.
7. Do not include inline citations, source labels, tables, or a section named "Answer".

{context_window}

--- Context Documents ---
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
    context_window: str = "",
    user_role: str = "employee",
) -> str:
    context = build_context_string(retrieved_chunks, question)
    
    if user_role == "admin":
        persona = ADMIN_PERSONA
    else:
        persona = EMPLOYEE_PERSONA

    structure_hint = ""
    if answer_plan:
        if answer_plan.question_type == "calc":
            structure_hint = "\nPreferred structure: heading, direct result summary, then numbered steps."
        elif answer_plan.question_type == "compare":
            structure_hint = "\nPreferred structure: heading, direct comparison summary, then bullets grouped by comparison label."
        elif answer_plan.question_type == "eligibility":
            structure_hint = "\nPreferred structure: heading, direct eligibility summary, then bullet points listing the deciding conditions."
        elif answer_plan.question_type == "explain":
            structure_hint = "\nPreferred structure: heading, short explanation summary, then key points."
        
    return SYSTEM_PROMPT_TEMPLATE.format(
        persona=persona,
        context_window=f"{context_window}{structure_hint}",
        context=context
    )


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
