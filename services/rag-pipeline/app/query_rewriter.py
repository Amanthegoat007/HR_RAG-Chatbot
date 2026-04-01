"""
Legacy helper module.

The live production path resolves follow-ups and document focus through
context_resolver.py. This module is kept only for backward compatibility
and offline experimentation, and it should not be treated as the runtime
source of truth for conversational resolution.
"""

import logging
import re
import time
from typing import Any, Tuple
import httpx

from app.llm_client import generate_text

logger = logging.getLogger(__name__)

# Common HR abbreviations mapping for rule-based instant expansion
HR_ABBREVIATIONS = {
    "wfh": "Work From Home",
    "pto": "Paid Time Off",
    "ot": "Overtime",
    "kpi": "Key Performance Indicator",
    "ctc": "Cost to Company",
    "lwp": "Leave Without Pay",
    "hr": "Human Resources",
    "sop": "Standard Operating Procedure",
    "nda": "Non-Disclosure Agreement",
    "hmo": "Health Maintenance Organization",
    "loa": "Leave of Absence",
    "np": "Notice Period",
}

SYS_PROMPT_REWRITE = """You are an intelligent query rewriter for an HR assistant.
Your job is to rewrite the user's latest query to make it fully self-contained, resolving any pronouns ("it", "they") or vague references ("that policy") using the provided conversation history.
Also ensure HR acronyms are understood.

CRITICAL RULES:
1. NEVER use <think> tags. Do not explain your reasoning.
2. DO NOT output conversational filler like "Here is the rewritten query:".
3. Output ONLY the raw rewritten string, nothing else. If it does not need rewriting, output the original string exactly.

Conversation History:
{history}
"""

async def rewrite_query(
    query: str,
    conversation_history: list[dict[str, Any]],
    http_client: httpx.AsyncClient,
) -> Tuple[str, bool]:
    """
    Rewrite a query based on conversation history.
    Returns: (rewritten_query: str, was_rewritten: bool)
    """
    original_query = query.strip()
    
    # 1. Expand abbreviations right away using word boundaries
    expanded_query = original_query
    for abbr, full_form in HR_ABBREVIATIONS.items():
        pattern = re.compile(rf"\b{abbr}\b", re.IGNORECASE)
        expanded_query = pattern.sub(full_form, expanded_query)
    
    # If no history, just return expanded query
    if not conversation_history:
        return expanded_query, expanded_query != original_query
        
    # Check if query needs context resolution (heuristics)
    needs_llm = False
    
    # If query is very short, likely a follow up
    if len(original_query.split()) <= 4:
        needs_llm = True
        
    # Look for pronouns/anaphora
    anaphora_markers = ["it", "they", "them", "that", "this", "these", "those", "he", "she", "what about", "how about", "same"]
    lower_query = original_query.lower()
    if any(re.search(rf"\b{marker}\b", lower_query) for marker in anaphora_markers):
        needs_llm = True
        
    if not needs_llm:
        return expanded_query, expanded_query != original_query
        
    # Build history string
    history_str = ""
    for msg in conversation_history[-4:]:  # Use last 2 turns
        role = "User" if msg["role"] == "user" else "Assistant"
        # Truncate assistant messages to extract just the topic context
        content = msg["content"]
        if role == "Assistant" and len(content) > 200:
            content = content[:200] + "..."
        history_str += f"{role}: {content}\n"
        
    prompt = SYS_PROMPT_REWRITE.format(history=history_str)
    
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Rewrite this query: {expanded_query}"}
    ]
    
    try:
        start_time = time.time()
        rewritten = await generate_text(
            client=http_client,
            messages=messages,
            max_tokens=60,
            temperature=0.0,  # Zero temp for consistent rewrites
            enable_thinking=False,
        )
        elapsed = time.time() - start_time
        
        # Clean up possible LLM artifacts
        # Simply strip whitespace and bounding quotes
        rewritten = rewritten.strip()
        rewritten = re.sub(r'^["\']|["\']$', '', rewritten)
        rewritten = re.sub(r'^\*\*|\*\*$', '', rewritten)
        
        if not rewritten or rewritten.lower() == expanded_query.lower():
            return expanded_query, expanded_query != original_query
            
        logger.info("Query rewritten", extra={
            "original": original_query,
            "rewritten": rewritten,
            "elapsed_ms": round(elapsed * 1000)
        })
        return rewritten, True
        
    except Exception as exc:
        logger.error("Failed to rewrite query, falling back to original", extra={"error": str(exc)})
        return expanded_query, expanded_query != original_query
