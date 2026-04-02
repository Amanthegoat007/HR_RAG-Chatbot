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
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, Literal

import httpx
from qdrant_client import AsyncQdrantClient

from app.answer_planner import classify_question, plan_answer, render_answer_plan
from app.cache import ContextResolutionCache, SemanticCache
from app.config import settings
from app.context_resolver import (
    build_turn_context,
    resolve_conversation_context,
    serialize_context_resolution,
)
from app.context_selector import select_context_chunks
from app.embedding_service import embedding_service
from app.generation_policy import GenerationPolicy, choose_generation_policy
from app.hyde_generator import generate_hyde_document
from app.llm_client import LLMUnavailableError, generate_stream, LLMStreamChunk
from app.prompt_templates import build_prompt, format_as_mistral_chat
from app.reranker_service import reranker_service
from app.retriever import hybrid_search
from app.sse_handler import (
    make_error_event,
    make_done_event,
    make_sources_event,
    make_stage_event,
    make_token_event,
    strip_leading_reasoning_artifacts,
)

logger = logging.getLogger(__name__)


@dataclass
class GenerationAttemptResult:
    answer_tokens: list[str] = field(default_factory=list)
    buffered_visible_text: str = ""
    buffer_flushed: bool = False
    visible_token_count: int = 0
    reasoning_token_count: int = 0
    first_visible_token_latency_ms: int | None = None
    generation_latency_ms: int = 0

    @property
    def answer_text(self) -> str:
        return "".join(self.answer_tokens)

    @property
    def normalized_answer_text(self) -> str:
        return _normalize_generated_answer(self.answer_text)


class DeepModeRetryRequested(Exception):
    def __init__(self, reason: Literal["no_visible_tokens", "empty_answer", "title_only_answer"]):
        super().__init__(reason)
        self.reason = reason


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


def _estimate_token_count(text: str) -> int:
    pieces = re.findall(r"\w+|[^\w\s]", text or "", flags=re.UNICODE)
    return len(pieces)


def _normalize_generated_answer(text: str) -> str:
    cleaned = (text or "").replace(settings.llm_stop_sequence, "")
    cleaned = strip_leading_reasoning_artifacts(cleaned).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _is_title_only_answer(text: str) -> bool:
    cleaned = _normalize_generated_answer(text)
    if not cleaned:
        return False

    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*(?:\n+|$)([\s\S]*)$", cleaned)
    if not match:
        return False

    body = match.group(2).strip()
    if not body and "not available" in match.group(1).lower():
        return False
    return not body


def _invalid_answer_reason(text: str) -> Literal["empty_answer", "title_only_answer"] | None:
    cleaned = _normalize_generated_answer(text)
    if not cleaned:
        return "empty_answer"
    if _is_title_only_answer(cleaned):
        return "title_only_answer"
    return None


def _should_flush_deep_buffer(text: str) -> bool:
    cleaned = (text or "").lstrip()
    if not cleaned:
        return False

    if not cleaned.startswith("##"):
        return len(cleaned) >= 12

    match = re.match(r"^\s{0,3}#{1,6}\s+.+?(?:\n+|$)([\s\S]*)$", cleaned)
    if not match:
        return False

    body = re.sub(r"\s+", " ", match.group(1)).strip()
    return len(body) >= 12


from qdrant_client import models

async def _expand_with_neighbors(
    qdrant_client: AsyncQdrantClient,
    selected_chunks: list[dict[str, Any]],
    all_retrieved_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Sentence Window Retrieval: expand each selected chunk with its
    immediate neighbors (chunk_index ± 1) from the same document.

    If neighbors are not in the already-retrieved pool, queries Qdrant
    to fetch them directly so the LLM ALWAYS gets the full context.
    """
    if not selected_chunks:
        return selected_chunks

    # Build a fast lookup: (document_id, chunk_index) → chunk
    chunk_lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for chunk in all_retrieved_chunks:
        doc_id = chunk.get("document_id", "")
        ci = chunk.get("chunk_index", -1)
        if doc_id and ci >= 0:
            chunk_lookup[(doc_id, ci)] = chunk

    # Identify which neighbors are missing
    missing_neighbors = set()
    for chunk in selected_chunks:
        doc_id = chunk.get("document_id", "")
        ci = chunk.get("chunk_index", -1)
        if not doc_id or ci < 0:
            continue
            
        if ci > 0 and (doc_id, ci - 1) not in chunk_lookup:
            missing_neighbors.add((doc_id, ci - 1))
        if (doc_id, ci + 1) not in chunk_lookup:
            missing_neighbors.add((doc_id, ci + 1))

    # Fetch missing neighbors from Qdrant
    if missing_neighbors:
        should_conds = []
        for doc_id, c_idx in missing_neighbors:
            should_conds.append(
                models.Filter(
                    must=[
                        models.FieldCondition(key="document_id", match=models.MatchValue(value=doc_id)),
                        models.FieldCondition(key="chunk_index", match=models.MatchValue(value=c_idx)),
                    ]
                )
            )
        
        try:
            scroll_res, _ = await qdrant_client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=models.Filter(should=should_conds),
                limit=len(missing_neighbors) * 2,
                with_payload=True,
                with_vectors=False
            )
            for point in scroll_res:
                if point.payload:
                    doc_id = point.payload.get("document_id", "")
                    c_idx = point.payload.get("chunk_index", -1)
                    if doc_id and c_idx >= 0:
                        chunk_lookup[(doc_id, c_idx)] = point.payload
        except Exception as e:
            logger.warning("Failed to fetch missing neighbors from Qdrant", extra={"error": str(e)})

    expanded: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for chunk in selected_chunks:
        doc_id = chunk.get("document_id", "")
        ci = chunk.get("chunk_index", -1)
        key = chunk.get("point_id") or f"{doc_id}:{ci}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        parts: list[str] = []
        prev_chunk = chunk_lookup.get((doc_id, ci - 1)) if doc_id and ci > 0 else None
        next_chunk = chunk_lookup.get((doc_id, ci + 1)) if doc_id else None

        if prev_chunk and prev_chunk.get("point_id", "") not in seen_keys:
            prev_text = prev_chunk.get("text", "").strip()
            if prev_text:
                parts.append(prev_text)

        parts.append(chunk.get("text", "").strip())

        if next_chunk and next_chunk.get("point_id", "") not in seen_keys:
            next_text = next_chunk.get("text", "").strip()
            if next_text:
                parts.append(next_text)

        expanded_chunk = {**chunk, "text": "\n\n".join(parts)}
        expanded.append(expanded_chunk)

    return expanded


async def _stream_generation_attempt(
    http_client: httpx.AsyncClient,
    messages: list[dict[str, str]],
    generation_policy: GenerationPolicy,
    result: GenerationAttemptResult,
) -> AsyncGenerator[Any, None]:
    start_time = time.monotonic()
    chunk_generator = generate_stream(
        http_client,
        messages,
        max_tokens=generation_policy.max_tokens,
        stop=generation_policy.stop,
        temperature=generation_policy.temperature,
        enable_thinking=generation_policy.reasoning_mode == "deep",
    )

    try:
        while True:
            try:
                if generation_policy.reasoning_mode == "deep" and result.visible_token_count == 0:
                    remaining = (
                        settings.llm_deep_first_visible_timeout_seconds
                        - (time.monotonic() - start_time)
                    )
                    if remaining <= 0:
                        raise DeepModeRetryRequested("no_visible_tokens")
                    chunk = await asyncio.wait_for(chunk_generator.__anext__(), timeout=remaining)
                else:
                    chunk = await chunk_generator.__anext__()
            except asyncio.TimeoutError as exc:
                raise DeepModeRetryRequested("no_visible_tokens") from exc
            except StopAsyncIteration:
                break

            if chunk.reasoning_content:
                result.reasoning_token_count += _estimate_token_count(chunk.reasoning_content)
                if (
                    generation_policy.reasoning_mode == "deep"
                    and result.visible_token_count == 0
                    and result.reasoning_token_count >= settings.llm_deep_reasoning_token_limit_before_fallback
                ):
                    raise DeepModeRetryRequested("no_visible_tokens")

            if not chunk.content:
                continue

            visible_token = (
                strip_leading_reasoning_artifacts(chunk.content)
                if result.visible_token_count == 0
                else chunk.content
            )
            if not visible_token:
                continue

            if result.first_visible_token_latency_ms is None:
                result.first_visible_token_latency_ms = round((time.monotonic() - start_time) * 1000)

            result.visible_token_count += _estimate_token_count(visible_token)
            result.answer_tokens.append(visible_token)

            if generation_policy.reasoning_mode == "deep" and not result.buffer_flushed:
                result.buffered_visible_text += visible_token
                if _should_flush_deep_buffer(result.buffered_visible_text):
                    yield make_token_event(result.buffered_visible_text)
                    result.buffered_visible_text = ""
                    result.buffer_flushed = True
                continue

            yield make_token_event(visible_token)

    finally:
        result.generation_latency_ms = round((time.monotonic() - start_time) * 1000)
        try:
            await chunk_generator.aclose()
        except Exception:
            pass


def _working_set_documents(working_set: dict[str, Any] | None) -> list[dict[str, Any]]:
    documents = (working_set or {}).get("session_documents") or []
    return [document for document in documents if isinstance(document, dict)]


def _working_set_document_by_id(
    working_set: dict[str, Any] | None,
    document_id: str | None,
) -> dict[str, Any] | None:
    if not document_id:
        return None
    for document in _working_set_documents(working_set):
        if document.get("document_id") == document_id:
            return document
    return None


def _document_status_message(context_resolution, working_set: dict[str, Any] | None) -> str:
    document = _working_set_document_by_id(working_set, context_resolution.focus_id)
    label = (
        (document or {}).get("display_name")
        or context_resolution.focus_label
        or "the uploaded document"
    )
    status = (document or {}).get("status") or "unknown"

    if status in {"pending", "normalizing", "processing", "embedding"}:
        return (
            f"{label} is still processing for this conversation. "
            "Please try again in a moment once indexing finishes."
        )
    if status == "needs_review":
        return (
            f"{label} needs review before I can explain it reliably. "
            "The parser could not extract enough trustworthy text from the upload."
        )
    if status == "failed":
        return (
            f"{label} could not be processed for this conversation. "
            "Please re-upload a clearer file and try again."
        )
    if not document:
        return (
            "I do not see a ready uploaded document in this conversation yet. "
            "Upload a file here first, then ask me to explain it."
        )
    return (
        f"I found {label}, but it is not ready to answer from yet. "
        "Please try again in a moment."
    )


def _document_focus_metadata(context_resolution, *, query_mode: str) -> dict[str, Any] | None:
    if context_resolution.focus_type != "document":
        return None
    return {
        "document_id": context_resolution.focus_id,
        "display_name": context_resolution.focus_label,
        "resolution_source": context_resolution.focus_source or context_resolution.source,
        "query_mode": query_mode,
    }


def _assistant_direct_message(context_resolution) -> str:
    if context_resolution.assistant_response:
        return context_resolution.assistant_response

    style = context_resolution.assistant_response_style
    if style == "greeting_warm" or context_resolution.interaction_type == "greeting":
        return (
            "Hi. I can help with HR policies, benefits, leave, payroll, onboarding, "
            "and uploaded documents in this conversation."
        )
    if style == "capability_overview" or context_resolution.interaction_type == "capability":
        return (
            "I can help with HR policies, benefits, leave, payroll, onboarding, and "
            "uploaded documents in this conversation. Ask a policy question or upload "
            "a document for me to explain."
        )
    if style == "acknowledgement_positive" or context_resolution.interaction_type == "acknowledgement":
        return "Glad to help. Ask another HR question or upload a document anytime."
    if style == "closing_helpful" or context_resolution.interaction_type == "closing":
        return "Happy to help. Come back anytime with another HR policy or document question."
    return "I can help with HR policies, benefits, leave, payroll, onboarding, and uploaded documents."


def _is_low_information_query(query: str, interaction_type: str | None) -> bool:
    if interaction_type in {"greeting", "acknowledgement", "capability", "closing"}:
        return True
    normalized = " ".join((query or "").lower().split())
    if not normalized:
        return True
    tokens = re.findall(r"\w+", normalized)
    if len(tokens) > 3:
        return False
    if any(term in normalized for term in ("policy", "document", "file", "upload", "uploaded")):
        return False
    hr_terms = (
        "leave",
        "pto",
        "benefit",
        "benefits",
        "payroll",
        "probation",
        "onboarding",
        "salary",
        "insurance",
        "medical",
        "holiday",
        "ticket",
        "gratuity",
        "reimbursement",
        "allowance",
        "contract",
        "offer",
    )
    return not any(term in normalized for term in hr_terms)


def _top_rerank_score(reranked_chunks: list[dict[str, Any]]) -> float:
    if not reranked_chunks:
        return 0.0
    top = reranked_chunks[0]
    return float(top.get("rerank_score") or top.get("score") or 0.0)


def _assistant_direct_meta(
    *,
    question_type: str,
    requested_reasoning_mode: Literal["fast", "deep"],
    context_resolution,
    focus_meta: dict[str, Any],
    answer_text: str,
    reason: str | None = None,
) -> dict[str, Any]:
    metadata = {
        "question_type": question_type,
        "reasoning_mode": requested_reasoning_mode,
        "requested_reasoning_mode": requested_reasoning_mode,
        "effective_reasoning_mode": requested_reasoning_mode,
        "answer_path": "assistant_direct",
        "deep_fallback_applied": False,
        "router_confidence": context_resolution.confidence,
        "context_resolution": serialize_context_resolution(context_resolution),
        "focus": focus_meta,
        "interaction_type": context_resolution.interaction_type,
        "turn_context": build_turn_context(
            question=context_resolution.standalone_query or "",
            answer_text=answer_text,
            question_type=question_type,
            source_chunks=[],
            context_resolution=context_resolution,
        ),
    }
    if reason:
        metadata["relevance_guard_reason"] = reason
    return metadata


async def run_query_pipeline(
    query: str,
    document_id: Optional[str],
    http_client: httpx.AsyncClient,
    qdrant_client: AsyncQdrantClient,
    cache: SemanticCache,
    context_resolution_cache: ContextResolutionCache | None = None,
    conversation_history: list | None = None,
    conversation_id: Optional[str] = None,
    user_role: str = "employee",
    session_id: Optional[str] = None,
    session_scope_active: bool = False,
    conversation_working_set: dict[str, Any] | None = None,
    reasoning_mode: Optional[Literal["fast", "deep"]] = None,
) -> AsyncGenerator[Any, None]:
    if hasattr(conversation_working_set, "model_dump"):
        conversation_working_set = conversation_working_set.model_dump()
    
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
    initial_question_type = classify_question(normalized_query)
    requested_reasoning_mode: Literal["fast", "deep"] = (
        reasoning_mode if reasoning_mode in {"fast", "deep"} else "fast"
    )
    logger.info(
        "RAG pipeline started",
        extra={
            "query_len": len(normalized_query),
            "document_scoped": document_id is not None,
            "question_type": initial_question_type,
            "requested_reasoning_mode": requested_reasoning_mode,
        },
    )

    # ── Stage: Understanding ─────────────────────────────────────────────────
    yield make_stage_event("understanding", "Resolving conversation context...", "active")

    context_resolution = await resolve_conversation_context(
        normalized_query,
        conversation_history or [],
        http_client=http_client,
        cache=context_resolution_cache,
        conversation_id=conversation_id,
        session_scope_active=session_scope_active,
        conversation_working_set=conversation_working_set,
    )
    question_type = classify_question(
        context_resolution.standalone_query or normalized_query,
    )
    focus_meta = {
        "type": context_resolution.focus_type,
        "id": context_resolution.focus_id,
        "label": context_resolution.focus_label,
    }
    if context_resolution.action == "direct_response":
        assistant_text = _assistant_direct_message(context_resolution)
        assistant_meta = _assistant_direct_meta(
            question_type=question_type,
            requested_reasoning_mode=requested_reasoning_mode,
            context_resolution=context_resolution,
            focus_meta=focus_meta,
            answer_text=assistant_text,
        )
        yield make_stage_event("understanding", "Ready to help", "done")
        yield make_token_event(assistant_text)
        yield make_sources_event([])
        yield make_done_event(assistant_meta)
        return

    if context_resolution.clarification_needed:
        clarification_meta = {
            "question_type": question_type,
            "reasoning_mode": requested_reasoning_mode,
            "requested_reasoning_mode": requested_reasoning_mode,
            "effective_reasoning_mode": requested_reasoning_mode,
            "answer_path": "clarification",
            "deep_fallback_applied": False,
            "context_resolution": serialize_context_resolution(context_resolution),
            "focus": focus_meta,
            "interaction_type": context_resolution.interaction_type,
            "turn_context": {
                "active_subject": context_resolution.active_subject,
                "latest_topic_reference": context_resolution.latest_topic_reference,
                "recent_summary": context_resolution.clarification_question,
                "question_type": question_type,
                "unresolved_references": context_resolution.unresolved_references,
                "focus_type": context_resolution.focus_type,
                "focus_id": context_resolution.focus_id,
                "focus_label": context_resolution.focus_label,
                "interaction_type": context_resolution.interaction_type,
            },
        }
        yield make_stage_event("understanding", "Need clarification", "done")
        yield make_token_event(context_resolution.clarification_message or "")
        yield make_sources_event([])
        yield make_done_event(clarification_meta)
        return

    if context_resolution.action == "status_only":
        status_message = _document_status_message(
            context_resolution,
            conversation_working_set,
        )
        status_meta = {
            "question_type": question_type,
            "reasoning_mode": requested_reasoning_mode,
            "requested_reasoning_mode": requested_reasoning_mode,
            "effective_reasoning_mode": requested_reasoning_mode,
            "answer_path": "document_status",
            "deep_fallback_applied": False,
            "context_resolution": serialize_context_resolution(context_resolution),
            "focus": focus_meta,
            "interaction_type": context_resolution.interaction_type,
            "document_focus": _document_focus_metadata(
                context_resolution,
                query_mode="status_only",
            ),
            "turn_context": {
                "active_subject": context_resolution.active_subject,
                "latest_topic_reference": context_resolution.latest_topic_reference,
                "recent_summary": status_message,
                "question_type": question_type,
                "unresolved_references": context_resolution.unresolved_references,
                "focus_type": context_resolution.focus_type,
                "focus_id": context_resolution.focus_id,
                "focus_label": context_resolution.focus_label,
                "interaction_type": context_resolution.interaction_type,
            },
        }
        yield make_stage_event("understanding", "Attachment linked", "done")
        yield make_token_event(status_message)
        yield make_sources_event([])
        yield make_done_event(status_meta)
        return

    standalone_query = context_resolution.standalone_query or normalized_query
    retrieval_document_id = document_id
    if (
        not retrieval_document_id
        and context_resolution.focus_type == "document"
        and context_resolution.focus_id
        and context_resolution.action == "retrieve"
    ):
        retrieval_document_id = context_resolution.focus_id
    allow_semantic_cache = (
        not retrieval_document_id
        and not _is_low_information_query(standalone_query, context_resolution.interaction_type)
    )
    hyde_doc = await generate_hyde_document(standalone_query, http_client)
    yield make_stage_event(
        "understanding",
        "Attachment linked"
        if context_resolution.focus_type == "document" and context_resolution.focus_id
        else "Context linked",
        "done",
    )

    # ── Stage: Embedding ─────────────────────────────────────────────────────
    yield make_stage_event("embedding", "Embedding query...", "active")

    # ── Step 2: Semantic Cache Check ─────────────────────────────────────────
    # Get the embedding first, doing it in process now
    try:
        texts_to_embed = [standalone_query]
        if hyde_doc:
            texts_to_embed.append(hyde_doc)
            
        embed_results = await embedding_service.embed_texts_async(
            texts=texts_to_embed,
            batch_size=len(texts_to_embed)
        )
        
        dense_vector = embed_results[0]["dense"]["values"]
        sparse_indices = embed_results[0]["sparse"]["indices"]
        sparse_values = embed_results[0]["sparse"]["values"]
        
        hyde_dense = embed_results[1]["dense"]["values"] if hyde_doc else None
        hyde_sparse_indices = embed_results[1]["sparse"]["indices"] if hyde_doc else None
        hyde_sparse_values = embed_results[1]["sparse"]["values"] if hyde_doc else None
        
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
    library_generation = 0
    conversation_generation: int | None = None
    if allow_semantic_cache:
        library_generation, conversation_generation = await cache.get_generation_snapshot(
            conversation_id if session_scope_active else None
        )
        cached_result = await cache.get(
            dense_vector,
            partition=requested_reasoning_mode,
            library_generation=library_generation,
            conversation_generation=conversation_generation,
        )
        if cached_result:
            logger.info("Cache HIT — returning cached answer")
            cached_answer = strip_leading_reasoning_artifacts(cached_result.get("answer", ""))
            cached_sources = cached_result.get("sources", [])
            cached_meta = dict(cached_result.get("meta", {}) or {})
            cached_meta.setdefault("requested_reasoning_mode", requested_reasoning_mode)
            cached_meta.setdefault(
                "effective_reasoning_mode",
                cached_meta.get("reasoning_mode", requested_reasoning_mode),
            )
            cached_meta["reasoning_mode"] = cached_meta.get("effective_reasoning_mode", "fast")
            cached_meta.setdefault("deep_fallback_applied", False)

            if _invalid_answer_reason(cached_answer):
                logger.warning("Ignoring invalid cached answer", extra={"cache_key": cached_result.get("cache_key")})
            else:

                # Stream cached answer as a single token event
                # (We could split into individual tokens but it's not worth the complexity)
                yield make_token_event(cached_answer)
                yield make_sources_event(cached_sources)
                yield make_done_event(cached_meta)
                return

    logger.debug("Cache MISS — running full RAG pipeline")

    # ── Stage: Searching ──────────────────────────────────────────────────────
    yield make_stage_event("searching", "Searching documents...", "active")

    # ── Step 3: Hybrid Retrieval (Qdrant) ─────────────────────────────────────
    try:
        retrieved_chunks = await hybrid_search(
            qdrant_client=qdrant_client,
            http_client=http_client,
            dense_vector=dense_vector,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            top_k=settings.retrieval_rerank_top_n,
            document_id_filter=retrieval_document_id,
            session_id_filter=None if retrieval_document_id else session_id,
            hyde_dense_vector=hyde_dense,
            hyde_sparse_indices=hyde_sparse_indices,
            hyde_sparse_values=hyde_sparse_values,
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
            f"I could not extract enough relevant content from {context_resolution.focus_label or 'the uploaded document'}."
            if retrieval_document_id and context_resolution.focus_type == "document"
            else "This information is not available in the current HR knowledge base."
        )
        no_context_meta = {
            "answer_path": "document_no_context" if retrieval_document_id else "no_context",
            "question_type": question_type,
            "reasoning_mode": requested_reasoning_mode,
            "requested_reasoning_mode": requested_reasoning_mode,
            "effective_reasoning_mode": requested_reasoning_mode,
            "deep_fallback_applied": False,
            "deterministic_confidence": 0.0,
            "context_resolution": serialize_context_resolution(context_resolution),
            "focus": focus_meta,
            "interaction_type": context_resolution.interaction_type,
            "document_focus": _document_focus_metadata(
                context_resolution,
                query_mode="document_scoped" if retrieval_document_id else "normal",
            ),
            "turn_context": build_turn_context(
                question=standalone_query,
                answer_text=no_context_message,
                question_type=question_type,
                source_chunks=[],
                context_resolution=context_resolution,
            ),
        }
        yield make_token_event(no_context_message)
        yield make_sources_event([])
        yield make_done_event(no_context_meta)
        return

    yield make_stage_event("searching", "Documents found", "done")

    # ── Stage: Reranking ──────────────────────────────────────────────────────
    yield make_stage_event("reranking", "Reranking results...", "active")

    # ── Step 4: Cross-Encoder Reranking ────────────────────────────────────
    try:
        rerank_top_n = settings.top_n_rerank
        if question_type == "calc":
            rerank_top_n = max(rerank_top_n, settings.top_n_rerank_calc)
        elif question_type == "list":
            rerank_top_n = max(rerank_top_n, settings.top_n_rerank_list)

        docs_for_reranker = [
            {
                "text": chunk.get("text", ""),
                "metadata": chunk.get("metadata", {}),
                "document_id": chunk.get("document_id", "")
            }
            for chunk in retrieved_chunks
        ]
        
        ranked = await reranker_service.rerank_async(
            query=standalone_query,
            documents=docs_for_reranker,
            top_n=rerank_top_n,
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
            for idx, chunk in enumerate(retrieved_chunks[:rerank_top_n])
        ]

    yield make_stage_event("reranking", "Results ranked", "done")

    top_rerank_score = _top_rerank_score(reranked_chunks)
    if (
        not retrieval_document_id
        and _is_low_information_query(standalone_query, context_resolution.interaction_type)
        and top_rerank_score < settings.score_threshold
    ):
        redirect_text = (
            "I can help with HR policies, benefits, leave, payroll, onboarding, and uploaded documents. "
            "Ask me a specific HR question and I'll jump in."
        )
        redirect_meta = _assistant_direct_meta(
            question_type=question_type,
            requested_reasoning_mode=requested_reasoning_mode,
            context_resolution=context_resolution,
            focus_meta=focus_meta,
            answer_text=redirect_text,
            reason="low_information_low_relevance",
        )
        yield make_stage_event("generating", "Need a more specific HR question", "done")
        yield make_token_event(redirect_text)
        yield make_sources_event([])
        yield make_done_event(redirect_meta)
        return

    # ── Stage: Generating ─────────────────────────────────────────────────────
    yield make_stage_event("generating", "Generating response...", "active")

    answer_plan = plan_answer(
        query=standalone_query,
        retrieved_chunks=retrieved_chunks,
        reranked_chunks=reranked_chunks,
    )
    selected_chunks = select_context_chunks(
        question_type=question_type,
        query=standalone_query,
        retrieved_chunks=retrieved_chunks,
        reranked_chunks=reranked_chunks,
        answer_plan=answer_plan,
    )

    # ── Neighbor Chunk Expansion (Sentence Window Retrieval) ──────────────────
    # For each selected chunk, look for chunk_index ± 1.
    # If not found in the already-retrieved pool, query Qdrant to fetch it.
    selected_chunks = await _expand_with_neighbors(
        qdrant_client,
        selected_chunks,
        retrieved_chunks
    )

    source_chunks = answer_plan.citation_chunks or selected_chunks
    generation_policy = choose_generation_policy(
        standalone_query,
        question_type=question_type,
        user_role=user_role,
        requested_reasoning_mode=requested_reasoning_mode,
        answer_path=answer_plan.answer_path,
    )
    response_meta = {
        "answer_path": "document_scoped" if retrieval_document_id else answer_plan.answer_path,
        "question_type": question_type,
        "reasoning_mode": generation_policy.reasoning_mode,
        "requested_reasoning_mode": requested_reasoning_mode,
        "effective_reasoning_mode": generation_policy.reasoning_mode,
        "deep_fallback_applied": False,
        "deterministic_confidence": round(answer_plan.deterministic_confidence, 3),
        "context_resolution": serialize_context_resolution(context_resolution),
        "focus": focus_meta,
        "interaction_type": context_resolution.interaction_type,
        "document_focus": _document_focus_metadata(
            context_resolution,
            query_mode="document_scoped" if retrieval_document_id else "normal",
        ),
    }

    if answer_plan.high_confidence and answer_plan.answer_path == "deterministic":
        deterministic_answer = render_answer_plan(answer_plan)
        response_meta["turn_context"] = build_turn_context(
            question=standalone_query,
            answer_text=deterministic_answer,
            question_type=question_type,
            source_chunks=source_chunks,
            context_resolution=context_resolution,
        )
        yield make_token_event(deterministic_answer)
        yield make_sources_event(source_chunks)
        yield make_done_event(response_meta)

        if allow_semantic_cache:
            try:
                await cache.set(
                    query_embedding=dense_vector,
                    answer=deterministic_answer,
                    sources=source_chunks,
                    meta=response_meta,
                    partition=response_meta["effective_reasoning_mode"],
                    library_generation=library_generation,
                    conversation_generation=conversation_generation,
                )
                logger.debug("Deterministic answer stored in semantic cache")
            except Exception as exc:
                logger.warning("Failed to cache deterministic answer", extra={"error": str(exc)})

        logger.info(
            "RAG pipeline complete",
            extra={
                "retrieved": len(retrieved_chunks),
                "reranked": len(reranked_chunks),
                "answer_path": "deterministic",
                "question_type": question_type,
            },
        )
        return

    
    context_window = context_resolution.context_window
    
    system_prompt_with_context = build_prompt(
        question=standalone_query,
        retrieved_chunks=selected_chunks,
        answer_plan=answer_plan,
        context_window=context_window,
        user_role=user_role,
    )
    
    # We pass the standalone query directly because the system prompt will answer it standalone
    messages = format_as_mistral_chat(
        system_prompt=system_prompt_with_context,
        question=standalone_query,
        conversation_history=[], # History is now in the context window!
    )

    if not settings.llm_adaptive_tokens_enabled:
        generation_policy = GenerationPolicy(
            reasoning_mode=generation_policy.reasoning_mode,
            profile="fixed",
            max_tokens=(
                settings.llm_max_tokens_deep_cap
                if generation_policy.reasoning_mode == "deep"
                else settings.llm_max_tokens
            ),
            stop=generation_policy.stop,
            temperature=generation_policy.temperature,
        )
    logger.debug(
        "Generation policy selected",
        extra={
            "reasoning_mode": generation_policy.reasoning_mode,
            "profile": generation_policy.profile,
            "max_tokens": generation_policy.max_tokens,
            "temperature": generation_policy.temperature,
            "stop_count": len(generation_policy.stop),
            "requested_reasoning_mode": requested_reasoning_mode,
        },
    )

    attempt_result = GenerationAttemptResult()
    try:
        try:
            async for sse_event in _stream_generation_attempt(
                http_client=http_client,
                messages=messages,
                generation_policy=generation_policy,
                result=attempt_result,
            ):
                yield sse_event
        except DeepModeRetryRequested as retry_exc:
            response_meta["deep_fallback_applied"] = True
            response_meta["deep_fallback_reason"] = retry_exc.reason
            yield make_stage_event(
                "generating",
                "Switching to fast response mode...",
                "active",
            )
            generation_policy = choose_generation_policy(
                standalone_query,
                question_type=question_type,
                user_role=user_role,
                requested_reasoning_mode="fast",
                answer_path=answer_plan.answer_path,
            )
            response_meta["effective_reasoning_mode"] = generation_policy.reasoning_mode
            response_meta["reasoning_mode"] = generation_policy.reasoning_mode
            attempt_result = GenerationAttemptResult()
            async for sse_event in _stream_generation_attempt(
                http_client=http_client,
                messages=messages,
                generation_policy=generation_policy,
                result=attempt_result,
            ):
                yield sse_event

        invalid_reason = _invalid_answer_reason(attempt_result.answer_text)
        if invalid_reason and requested_reasoning_mode == "deep" and not response_meta["deep_fallback_applied"]:
            response_meta["deep_fallback_applied"] = True
            response_meta["deep_fallback_reason"] = invalid_reason
            yield make_stage_event(
                "generating",
                "Retrying in fast mode...",
                "active",
            )
            generation_policy = choose_generation_policy(
                standalone_query,
                question_type=question_type,
                user_role=user_role,
                requested_reasoning_mode="fast",
                answer_path=answer_plan.answer_path,
            )
            response_meta["effective_reasoning_mode"] = generation_policy.reasoning_mode
            response_meta["reasoning_mode"] = generation_policy.reasoning_mode
            attempt_result = GenerationAttemptResult()
            async for sse_event in _stream_generation_attempt(
                http_client=http_client,
                messages=messages,
                generation_policy=generation_policy,
                result=attempt_result,
            ):
                yield sse_event
            invalid_reason = _invalid_answer_reason(attempt_result.answer_text)

        if invalid_reason:
            response_meta["deep_fallback_reason"] = invalid_reason
            error_text = (
                "I couldn't generate a reliable answer for this question. "
                "Please try again or rephrase it."
            )
            attempt_result = GenerationAttemptResult(answer_tokens=[error_text])
            yield make_token_event(error_text)

        if attempt_result.buffered_visible_text:
            yield make_token_event(attempt_result.buffered_visible_text)
            attempt_result.buffered_visible_text = ""

        response_meta["turn_context"] = build_turn_context(
            question=standalone_query,
            answer_text=attempt_result.normalized_answer_text,
            question_type=question_type,
            source_chunks=source_chunks,
            context_resolution=context_resolution,
        )
        response_meta["visible_token_count"] = attempt_result.visible_token_count
        response_meta["reasoning_token_count"] = attempt_result.reasoning_token_count
        if attempt_result.first_visible_token_latency_ms is not None:
            response_meta["first_visible_token_latency_ms"] = attempt_result.first_visible_token_latency_ms
        response_meta["generation_latency_ms"] = attempt_result.generation_latency_ms
        yield make_sources_event(source_chunks)
        yield make_done_event(response_meta)

    except LLMUnavailableError as exc:
        logger.error("All LLM providers unavailable", extra={"error": str(exc)})
        yield make_error_event(
            "The AI assistant is currently unavailable. Please try again later.",
            code="llm_unavailable",
        )
        yield make_done_event(response_meta)
        return

    # ── Post-pipeline: Store in Cache ────────────────────────────────────────
    final_answer = attempt_result.normalized_answer_text
    if final_answer and not _invalid_answer_reason(final_answer) and allow_semantic_cache:
        try:
            await cache.set(
                query_embedding=dense_vector,
                answer=final_answer,
                sources=source_chunks,
                meta=response_meta,
                partition=response_meta["effective_reasoning_mode"],
                library_generation=library_generation,
                conversation_generation=conversation_generation,
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
            "answer_tokens": attempt_result.visible_token_count,
            "reasoning_tokens": attempt_result.reasoning_token_count,
            "answer_path": response_meta.get("answer_path", "llm"),
            "question_type": question_type,
            "requested_reasoning_mode": requested_reasoning_mode,
            "effective_reasoning_mode": response_meta["effective_reasoning_mode"],
        },
    )
