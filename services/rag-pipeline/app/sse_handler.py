"""
============================================================================
FILE: services/rag-pipeline/app/sse_handler.py
PURPOSE: Server-Sent Events (SSE) builder for the query response stream.
         Returns plain SSE-formatted strings for maximum compatibility.
============================================================================
"""

import json
import logging
from typing import Any, AsyncGenerator
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    """Simple SSE event container that can be serialized to SSE format."""
    event: str
    data: str

    def encode(self) -> str:
        """Encode as SSE-formatted string."""
        return f"event: {self.event}\ndata: {self.data}\n\n"


def make_token_event(token: str) -> SSEEvent:
    return SSEEvent(
        event="token",
        data=json.dumps({"token": token}, ensure_ascii=False),
    )


def make_stage_event(stage: str, label: str, status: str = "active") -> SSEEvent:
    """
    Emit a pipeline stage progress event.
    stage:  e.g. "embedding", "searching", "reranking", "generating"
    label:  Human-readable label, e.g. "Embedding query..."
    status: "active" (in progress) or "done" (completed)
    """
    return SSEEvent(
        event="stage",
        data=json.dumps({"stage": stage, "label": label, "status": status}, ensure_ascii=False),
    )


def make_sources_event(chunks: list[dict[str, Any]]) -> SSEEvent:
    sources = []
    for chunk in chunks:
        source = {
            "filename": chunk.get("filename", ""),
            "section": chunk.get("section", ""),
            "page_number": chunk.get("page_number", 1),
            "document_id": chunk.get("document_id", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "score": round(chunk.get("rerank_score", chunk.get("score", 0.0)), 4),
            "text": chunk.get("text", "")[:500],  # Include chunk text for expandable cards (cap at 500 chars)
        }
        if chunk.get("heading_path"):
            source["heading_path"] = chunk["heading_path"]
        sources.append(source)

    return SSEEvent(
        event="sources",
        data=json.dumps({"sources": sources}, ensure_ascii=False),
    )


def make_error_event(message: str, code: str = "pipeline_error") -> SSEEvent:
    return SSEEvent(
        event="error",
        data=json.dumps({"error": message, "code": code}, ensure_ascii=False),
    )


def make_done_event() -> SSEEvent:
    return SSEEvent(
        event="done",
        data=json.dumps({"status": "complete"}),
    )


async def build_query_stream(
    token_generator: AsyncGenerator[str, None],
    source_chunks: list[dict[str, Any]],
) -> AsyncGenerator[SSEEvent, None]:
    """
    Compose the full SSE event stream for a query response.
    Yields SSEEvent objects: tokens → sources → done.
    """
    token_count = 0
    try:
        async for token in token_generator:
            yield make_token_event(token)
            token_count += 1

        yield make_sources_event(source_chunks)
        yield make_done_event()

        logger.debug(
            "SSE stream complete",
            extra={"token_count": token_count, "source_count": len(source_chunks)},
        )

    except Exception as exc:
        logger.error(
            "Error during SSE token streaming",
            extra={"error": str(exc), "tokens_sent": token_count},
        )
        yield make_error_event(
            message="An error occurred while generating the response. Please try again.",
            code="llm_stream_error",
        )
        yield make_done_event()
