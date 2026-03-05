"""
============================================================================
FILE: services/query/app/prompt_templates.py
PURPOSE: System prompt and context templates for the Mistral-7B LLM.
         Designed for factual, cited, bilingual HR knowledge responses.
ARCHITECTURE REF: §8 — Prompt Template
============================================================================
"""

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

SYSTEM_PROMPT = """You are an HR Knowledge Assistant. Answer questions using ONLY the provided context documents.

FORMAT RULES (FOLLOW STRICTLY):
1. Start with a one-line direct answer.
2. Use **bold** for all key terms, policy names, amounts, dates, and numbers.
3. When listing multiple items, ALWAYS use a numbered list (1. 2. 3.) with each item on its own line.
4. For each item in a list, bold the item name and add a dash before the description.
5. At the end of your answer, cite your source(s) on a new line: (Source: filename, Page X)
6. Keep answers clear and well-structured. Never dump raw text from the context.
7. If the answer is not in the context, say: "This information is not available in the current HR knowledge base."

EXAMPLE OUTPUT:
The main financial assistance programs are:

1. **Deferred Payment Agreement (DPA)** — For balances between **$100** and **$1,000**, with a **3-6 month** installment plan
2. **Extended Payment Plan (EPP)** — For larger balances, with a **6-12 month** interest-free plan
3. **Budget Billing Program** — Equal monthly payments based on a **12-month** average

(Source: Payment_Plans_Financial_Assistance.pdf, Page 2)

CONTEXT DOCUMENTS:
{context}

Answer the following question using the context above."""

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
