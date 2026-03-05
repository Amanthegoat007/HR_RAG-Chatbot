"""
============================================================================
FILE: services/query/app/pipeline.py
PURPOSE: Central RAG orchestrator — coordinates all pipeline steps from
         cache check through to SSE streaming.
ARCHITECTURE REF: §3 — Query Processing Pipeline (Steps 1–7)
DEPENDENCIES: httpx, qdrant-client, redis, all app.* modules
============================================================================

RAG Pipeline — Full Step Sequence:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 1: Normalize query text (lowercase + strip whitespace)            │
│  Step 2: Check semantic cache (Redis) → if HIT: stream cached answer   │
│  Step 3: Embed query → dense + sparse vectors (embedding-svc)          │
│  Step 4: Hybrid retrieval (Qdrant prefetch+RRF) → top-20 candidates    │
│  Step 5: Cross-encoder rerank (reranker-svc) → top-5 most relevant     │
│  Step 6: Build LLM prompt from system template + context chunks        │
│  Step 7: Call LLM (llama.cpp or Azure OpenAI) → stream tokens         │
│  Post:   Store answer in semantic cache; yield sources event           │
└─────────────────────────────────────────────────────────────────────────┘

Cache behavior:
  - Cache HIT: Return stored answer as a single token event, then sources.
    No retrieval, reranking, or LLM call needed.
  - Cache MISS: Run full pipeline. After complete answer is assembled,
    store (query_embedding, answer_text, source_chunks) in Redis.

Document scoping:
  - If document_id is provided in the request, restrict Qdrant search
    to only chunks from that document (filtered hybrid search).
  - Useful for "Ask about THIS document" feature in the frontend.
"""

import asyncio
import logging
from typing import Any, AsyncGenerator, Optional

import httpx
from qdrant_client import AsyncQdrantClient

from app.cache import SemanticCache
from app.config import settings
from app.embedding_service import embedding_service
from app.llm_client import LLMUnavailableError, generate_stream
from app.prompt_templates import build_prompt, format_as_mistral_chat
from app.reranker_service import reranker_service
from app.retriever import hybrid_search
from app.sse_handler import (
    build_query_stream,
    make_error_event,
    make_done_event,
    make_sources_event,
    make_stage_event,
    make_token_event,
)

logger = logging.getLogger(__name__)


def _normalize_query(query: str) -> str:
    """
    Normalize query text for cache key consistency.

    Removes leading/trailing whitespace and normalizes internal whitespace.
    Does NOT lowercase Arabic queries (Arabic is case-insensitive by nature
    but lowercasing may alter characters in edge cases).

    Args:
        query: Raw query string from the user.

    Returns:
        Normalized query string for consistent cache lookups.
    """
    # Collapse multiple internal spaces/tabs to single space
    return " ".join(query.split())


async def run_query_pipeline(
    query: str,
    document_id: Optional[str],
    http_client: httpx.AsyncClient,
    qdrant_client: AsyncQdrantClient,
    cache: SemanticCache,
) -> AsyncGenerator[Any, None]:
    """
    Execute the full RAG pipeline and yield SSE events.

    This is the central orchestrator called by the FastAPI endpoint.
    It manages all pipeline steps and returns an async generator of
    ServerSentEvent objects suitable for sse-starlette's EventSourceResponse.

    Architecture Reference: §3 — Steps 1-7 of the Query Processing Pipeline

    Args:
        query: User's natural language question (English or Arabic).
        document_id: Optional UUID to restrict search to one document.
        http_client: Shared httpx.AsyncClient for embedding + reranker + LLM calls.
        qdrant_client: Shared AsyncQdrantClient for vector search.
        cache: SemanticCache instance backed by Redis.

    Yields:
        ServerSentEvent objects: token → ... → sources → done
        On error: error → done
    """
    # ── Step 1: Normalize ────────────────────────────────────────────────────
    normalized_query = _normalize_query(query)
    logger.info(
        "RAG pipeline started",
        extra={
            "query_len": len(normalized_query),
            "document_scoped": document_id is not None,
        },
    )

    # ── Stage: Embedding ─────────────────────────────────────────────────────
    yield make_stage_event("embedding", "Embedding query...", "active")

    # ── Step 2: Semantic Cache Check ─────────────────────────────────────────
    # Get the embedding first, doing it in process now
    try:
        embed_result = embedding_service.embed_texts(
            texts=[normalized_query],
            batch_size=1
        )[0]
        
        dense_vector = embed_result["dense"]["values"]
        sparse_indices = embed_result["sparse"]["indices"]
        sparse_values = embed_result["sparse"]["values"]
    except Exception as exc:
        logger.error("Embedding service failed", extra={"error": str(exc)})
        yield make_error_event(
            "Failed to process your question. Please try again.",
            code="embedding_error",
        )
        yield make_done_event()
        return

    yield make_stage_event("embedding", "Query embedded", "done")

    # Check cache using the dense embedding as the lookup key
    # Only use cache for non-document-scoped queries (document-scoped answers
    # are document-specific and should not cross-contaminate the cache)
    if not document_id:
        cached_result = await cache.get(dense_vector)
        if cached_result:
            logger.info("Cache HIT — returning cached answer")
            cached_answer = cached_result.get("answer", "")
            cached_sources = cached_result.get("sources", [])

            # Stream cached answer as a single token event
            # (We could split into individual tokens but it's not worth the complexity)
            yield make_token_event(cached_answer)
            yield make_sources_event(cached_sources)
            yield make_done_event()
            return

    logger.debug("Cache MISS — running full RAG pipeline")

    # ── Stage: Searching ──────────────────────────────────────────────────────
    yield make_stage_event("searching", "Searching documents...", "active")

    # ── Step 3: Hybrid Retrieval (Qdrant) ─────────────────────────────────────
    try:
        retrieved_chunks = await hybrid_search(
            qdrant_client=qdrant_client,
            dense_vector=dense_vector,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            top_k=settings.retrieval_rerank_top_n,
            document_id_filter=document_id,
        )
    except Exception as exc:
        logger.error("Hybrid retrieval failed", extra={"error": str(exc)})
        yield make_error_event(
            "Failed to search the knowledge base. Please try again.",
            code="retrieval_error",
        )
        yield make_done_event()
        return

    if not retrieved_chunks:
        # No relevant documents found — inform user gracefully
        logger.info("No relevant chunks retrieved for query")
        no_context_message = (
            "I could not find relevant information in the HR knowledge base to answer "
            "your question. Please rephrase or contact the HR department directly."
        )
        yield make_token_event(no_context_message)
        yield make_sources_event([])
        yield make_done_event()
        return

    yield make_stage_event("searching", "Documents found", "done")

    # ── Stage: Reranking ──────────────────────────────────────────────────────
    yield make_stage_event("reranking", "Reranking results...", "active")

    # ── Step 4: Cross-Encoder Reranking ────────────────────────────────────
    try:
        docs_for_reranker = [
            {
                "text": chunk.get("text", ""),
                "metadata": chunk.get("metadata", {}),
                "document_id": chunk.get("document_id", "")
            }
            for chunk in retrieved_chunks
        ]
        
        ranked = reranker_service.rerank(
            query=normalized_query,
            documents=docs_for_reranker,
            top_n=settings.top_n_rerank,
        )
        
        # Merge rerank scores back into the ORIGINAL retrieved chunks
        # (which have filename, section, page_number, etc.)
        # Match by text content since reranker returns only text+score
        text_to_original = {chunk["text"]: chunk for chunk in retrieved_chunks}
        reranked_chunks = []
        for idx, ranked_doc in enumerate(ranked):
            original = text_to_original.get(ranked_doc["text"], {})
            reranked_chunks.append({
                **original,
                **ranked_doc,
                "rerank_score": ranked_doc.get("score", 0.0),
                "rerank_rank": ranked_doc.get("rank", idx + 1),
            })
    except Exception as exc:
        # Reranking failure is non-fatal: fall back to using retrieval order
        logger.warning(
            "Reranker failed — using retrieval order as fallback",
            extra={"error": str(exc)},
        )
        # Add dummy rerank scores so downstream code works
        reranked_chunks = [
            {**chunk, "rerank_score": chunk.get("score", 0.0), "rerank_rank": idx + 1}
            for idx, chunk in enumerate(retrieved_chunks[:settings.top_n_rerank])
        ]

    yield make_stage_event("reranking", "Results ranked", "done")

    # ── Stage: Generating ─────────────────────────────────────────────────────
    yield make_stage_event("generating", "Generating response...", "active")

    # ── Step 5: Build LLM Prompt ─────────────────────────────────────────────
    system_prompt_with_context = build_prompt(
        question=normalized_query,
        retrieved_chunks=reranked_chunks,
    )
    messages = format_as_mistral_chat(
        system_prompt=system_prompt_with_context,
        question=normalized_query,
    )

    # ── Step 6: Stream LLM Response + Collect for Cache ─────────────────────
    # We need to collect the full answer text to store it in the cache.
    # We do this by consuming the generator and yielding tokens simultaneously.
    answer_tokens: list[str] = []

    try:
        token_generator = generate_stream(http_client, messages)

        async for sse_event in build_query_stream(
            token_generator=token_generator,
            source_chunks=reranked_chunks,
        ):
            # Intercept token events to collect the answer text
            # (build_query_stream yields ServerSentEvent objects)
            if sse_event.event == "token":
                import json as _json
                try:
                    token_data = _json.loads(sse_event.data)
                    answer_tokens.append(token_data.get("token", ""))
                except Exception:
                    pass
            yield sse_event

    except LLMUnavailableError as exc:
        logger.error("All LLM providers unavailable", extra={"error": str(exc)})
        yield make_error_event(
            "The AI assistant is currently unavailable. Please try again later.",
            code="llm_unavailable",
        )
        yield make_done_event()
        return

    # ── Post-pipeline: Store in Cache ────────────────────────────────────────
    if answer_tokens and not document_id:
        full_answer = "".join(answer_tokens)
        try:
            await cache.set(
                query_embedding=dense_vector,
                answer=full_answer,
                sources=reranked_chunks,
            )
            logger.debug("Answer stored in semantic cache")
        except Exception as exc:
            # Cache write failure is non-fatal — the user already got their answer
            logger.warning("Failed to cache answer", extra={"error": str(exc)})

    logger.info(
        "RAG pipeline complete",
        extra={
            "retrieved": len(retrieved_chunks),
            "reranked": len(reranked_chunks),
            "answer_tokens": len(answer_tokens),
        },
    )
