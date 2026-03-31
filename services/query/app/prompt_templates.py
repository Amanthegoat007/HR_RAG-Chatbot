"""
============================================================================
FILE: services/query/app/prompt_templates.py
PURPOSE: System prompt and context templates for the Mistral-7B LLM.
         Designed for factual, cited, bilingual HR knowledge responses.
ARCHITECTURE REF: §8 — Prompt Template
============================================================================
"""

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------
# Design rationale:
# - "ONLY based on provided context" prevents hallucination of HR policies
# - Citation requirement enables verifiability and trust
# - Bilingual support (English + Arabic) for UAE workforce
# - Conservative temperature (0.1) set in config ensures deterministic answers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an HR Knowledge Assistant for UAE employees. You answer questions about HR policies, procedures, benefits, leave, and workplace guidelines based ONLY on the provided context documents.

RULES:
1. Answer ONLY based on the provided context. If the context does not contain the answer, say: "I don't have information about that in the current HR knowledge base. Please contact your HR representative for assistance."
2. Always cite your sources using the document filename and section/page number when available.
3. Be concise but thorough. Use bullet points for lists.
4. If a question is ambiguous, ask for clarification.
5. Never fabricate information, policies, or procedures.
6. Support both English and Arabic queries. Respond in the same language as the question.
7. For numerical data (leave balances, salary bands, etc.), quote the exact numbers from the documents.

CONTEXT DOCUMENTS:
{context}

Answer the following question based on the context above.
"""

# ---------------------------------------------------------------------------
# CONTEXT TEMPLATE
# ---------------------------------------------------------------------------
# Each retrieved chunk is formatted with this template before being included
# in the system prompt. The source attribution enables verifiable citations.
# ---------------------------------------------------------------------------

CONTEXT_TEMPLATE = """
---
Source: {filename} | Section: {section} | Page: {page_number}
---
{chunk_text}
"""


def build_context_string(retrieved_chunks: list[dict]) -> str:
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

    parts = []
    for chunk in retrieved_chunks:
        parts.append(CONTEXT_TEMPLATE.format(
            filename=chunk.get("filename", "Unknown"),
            section=chunk.get("section", "Unknown Section"),
            page_number=chunk.get("page_number", "?"),
            chunk_text=chunk.get("text", ""),
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
    context = build_context_string(retrieved_chunks)
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
