"""
============================================================================
FILE: services/query/app/sse_handler.py
PURPOSE: Server-Sent Events (SSE) builder for the query response stream.
         Formats token streams and the final sources payload for the client.
ARCHITECTURE REF: §3.8 — SSE Response Format
DEPENDENCIES: json, asyncio, sse-starlette
============================================================================

SSE Response Protocol:
━━━━━━━━━━━━━━━━━━━━━━
The client receives a stream of SSE events over a single HTTP connection.
Three event types are used:

  1. token events (while LLM is generating):
       event: token
       data: {"token": "Hello"}

  2. sources event (sent ONCE after the last token):
       event: sources
       data: {"sources": [{"filename": "...", "section": "...", "page_number": 5,
                            "document_id": "...", "chunk_index": 3, "score": 0.92}]}

  3. error event (sent if the pipeline fails mid-stream):
       event: error
       data: {"error": "LLM service unavailable", "code": "llm_error"}

SSE Format Specification (RFC 8895):
  Each event is:
      event: <event_type>
      data: <json_string>
      (blank line)

  sse-starlette handles the actual SSE protocol encoding.
  We just yield ServerSentEvent objects.

Client-Side Consumption (JavaScript example):
  const es = new EventSource('/query', {headers: {Authorization: `Bearer ${token}`}});
  es.addEventListener('token', e => appendToken(JSON.parse(e.data).token));
  es.addEventListener('sources', e => showSources(JSON.parse(e.data).sources));
  es.addEventListener('error', e => showError(JSON.parse(e.data).error));
"""

import json
import logging
from typing import Any, AsyncGenerator

from sse_starlette.sse import ServerSentEvent

logger = logging.getLogger(__name__)


def make_token_event(token: str) -> ServerSentEvent:
    """
    Build an SSE event carrying a single LLM token.

    Called once per token as they stream from the LLM.

    Args:
        token: A single text token from the LLM stream (e.g., "Hello", " world", "!").

    Returns:
        ServerSentEvent with event type "token" and JSON data payload.
    """
    return ServerSentEvent(
        event="token",
        data=json.dumps({"token": token}, ensure_ascii=False),
    )


def make_sources_event(chunks: list[dict[str, Any]]) -> ServerSentEvent:
    """
    Build an SSE event carrying source citations for the answer.

    Sent once after all tokens have been streamed. Contains enough metadata
    for the client to show: "Source: Annual Leave Policy.pdf, Page 3, §2.1 Leave Entitlement"

    Args:
        chunks: List of reranked chunk dicts. Expected keys per chunk:
            - "filename": str   — original document filename
            - "section": str    — section heading (may be empty)
            - "page_number": int — page number in original document
            - "document_id": str — UUID for deep-linking
            - "chunk_index": int — chunk position within document
            - "rerank_score": float — relevance score (optional, for debugging)
            - "heading_path": str  — breadcrumb like "Policy > §2 > §2.1" (optional)

    Returns:
        ServerSentEvent with event type "sources" and JSON data payload.
    """
    sources = []
    for chunk in chunks:
        source = {
            "filename": chunk.get("filename", ""),
            "section": chunk.get("section", ""),
            "page_number": chunk.get("page_number", 1),
            "document_id": chunk.get("document_id", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "score": round(chunk.get("rerank_score", chunk.get("score", 0.0)), 4),
        }
        # Include heading_path only if present (enriched by chunker)
        if chunk.get("heading_path"):
            source["heading_path"] = chunk["heading_path"]
        sources.append(source)

    return ServerSentEvent(
        event="sources",
        data=json.dumps({"sources": sources}, ensure_ascii=False),
    )


def make_error_event(message: str, code: str = "pipeline_error") -> ServerSentEvent:
    """
    Build an SSE event signalling a pipeline error to the client.

    Sent when the pipeline fails after the stream has already started
    (e.g., LLM drops the connection mid-generation). Since HTTP headers
    have already been sent, we can't return a 500 status; we use this event
    to inform the client so it can show a graceful error message.

    Args:
        message: Human-readable error description.
        code: Machine-readable error code for client-side handling.
              Common values: "llm_error", "retrieval_error", "cache_error"

    Returns:
        ServerSentEvent with event type "error" and JSON data payload.
    """
    return ServerSentEvent(
        event="error",
        data=json.dumps({"error": message, "code": code}, ensure_ascii=False),
    )


def make_done_event() -> ServerSentEvent:
    """
    Build a final SSE event to signal clean stream termination.

    This mirrors the [DONE] pattern used by OpenAI's API but as a named
    SSE event instead of a raw data line. Clients can use this to dismiss
    loading indicators.

    Returns:
        ServerSentEvent with event type "done" and empty data payload.
    """
    return ServerSentEvent(
        event="done",
        data=json.dumps({"status": "complete"}),
    )


async def build_query_stream(
    token_generator: AsyncGenerator[str, None],
    source_chunks: list[dict[str, Any]],
) -> AsyncGenerator[ServerSentEvent, None]:
    """
    Compose the full SSE event stream for a query response.

    Combines token events from the LLM with a final sources event.
    Handles mid-stream errors gracefully by emitting an error event.

    Stream sequence:
        token("Hello") → token(" ,") → token(" the") → ... → sources([...]) → done()

    Architecture Reference: §3.8 — SSE Response Format

    Args:
        token_generator: Async generator of token strings from llm_client.generate_stream().
        source_chunks: Reranked chunks to include as citations (from pipeline).

    Yields:
        ServerSentEvent objects in order: tokens → sources → done.
        On error: error event followed by done event.
    """
    token_count = 0
    try:
        async for token in token_generator:
            yield make_token_event(token)
            token_count += 1

        # All tokens received — send citations
        yield make_sources_event(source_chunks)
        yield make_done_event()

        logger.debug(
            "SSE stream complete",
            extra={"token_count": token_count, "source_count": len(source_chunks)},
        )

    except Exception as exc:
        # The stream has already started — we can't send an HTTP error status.
        # Instead, emit an error SSE event and close cleanly.
        logger.error(
            "Error during SSE token streaming",
            extra={"error": str(exc), "tokens_sent": token_count},
        )
        yield make_error_event(
            message="An error occurred while generating the response. Please try again.",
            code="llm_stream_error",
        )
        yield make_done_event()
