import logging
import time
import httpx
from typing import Optional

from app.llm_client import generate_text

logger = logging.getLogger(__name__)

SYS_PROMPT_HYDE = """You are an expert HR Policy Writer.
Write a brief, formal policy snippet that directly answers the user's question.
Do not write an introduction or conclusion. Write ONLY the hypothetical policy text itself.
Use formal HR terminology. Keep it under 3 sentences."""

async def generate_hyde_document(
    query: str,
    http_client: httpx.AsyncClient,
) -> Optional[str]:
    """
    Conditionally generates a hypothetical document based on the query.
    Only triggers for short/vague queries to minimize latency.
    """
    word_count = len(query.split())
    
    # Conditional logic: only use HyDE for short, vague queries (<= 5 words)
    # OR if the query contains colloquialisms like "stuff" or "rules"
    is_vague = word_count <= 5 or any(w in query.lower() for w in ["stuff", "rules", "thing", "info"])
    
    if not is_vague:
        return None
        
    messages = [
        {"role": "system", "content": SYS_PROMPT_HYDE},
        {"role": "user", "content": query}
    ]
    
    try:
        start_time = time.time()
        hypothetical_doc = await generate_text(
            client=http_client,
            messages=messages,
            max_tokens=60,
            temperature=0.3
        )
        elapsed = time.time() - start_time
        
        hypothetical_doc = hypothetical_doc.strip()
        if hypothetical_doc:
            logger.info("HyDE document generated", extra={
                "query": query,
                "elapsed_ms": round(elapsed * 1000)
            })
            return hypothetical_doc
            
    except Exception as exc:
        logger.error("HyDE generation failed", extra={"error": str(exc)})
        
    return None
