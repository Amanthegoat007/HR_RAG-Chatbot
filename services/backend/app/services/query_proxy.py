import httpx
import logging
import json
import re
from typing import Any, AsyncGenerator

import asyncpg
from fastapi import HTTPException

from app.config import settings
from app.services.response_formatter import normalize_markdown_answer
from app.services.assistant_enrichment import build_enriched_assistant_message_metadata

logger = logging.getLogger(__name__)

_EMPTY_RESPONSE_FALLBACK = (
    "I couldn't generate a reliable answer for this question. Please try again or rephrase it."
)


def _is_title_only_markdown(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False

    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*(?:\n+|$)([\s\S]*)$", cleaned)
    if not match:
        return False

    return not match.group(2).strip()


def _coerce_visible_answer_text(text: str) -> str:
    cleaned = normalize_markdown_answer(text)
    if not cleaned or _is_title_only_markdown(cleaned):
        return _EMPTY_RESPONSE_FALLBACK
    return cleaned


async def stream_rag_pipeline(
    message: str,
    conversation_history: list,
    conversation_id: str,
    http_client: httpx.AsyncClient | None = None,
    db_pool: asyncpg.Pool | None = None,
    language: str = "en",
    user_role: str = "employee",
    reasoning_mode: str | None = None,
    session_scope_active: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Proxy SSE events from the rag-pipeline to the client.
    Yields raw SSE-formatted strings that can be sent directly via StreamingResponse.

    Also yields a special internal event '__final__' at the end with the collected
    assistant text, so the caller can save it to the database.
    """
    payload = {
        "query": message,
        "conversation_id": conversation_id,
        "stream": True,
        "conversation_history": conversation_history or [],
        "user_role": user_role,
        "reasoning_mode": reasoning_mode,
        "session_scope_active": session_scope_active,
    }

    collected_tokens: list[str] = []
    latest_sources: list[dict] = []
    current_event: str | None = None
    done_meta: dict[str, Any] | None = None

    owns_http_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=300.0)
    try:
        async with client.stream(
            "POST",
            f"{settings.rag_pipeline_url}/query",
            json=payload
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line.strip():
                    continue

                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    continue

                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Collect tokens for DB save
                    if current_event == "token" and "token" in data:
                        collected_tokens.append(data["token"])
                        yield f"data: {json.dumps({'type': 'token', 'content': data['token']})}\n\n"

                    elif current_event == "stage" and "stage" in data:
                        yield f"data: {json.dumps({'type': 'stage', 'stage': data['stage'], 'label': data.get('label', ''), 'status': data.get('status', 'active')})}\n\n"

                    elif current_event == "sources" and "sources" in data:
                        latest_sources = data["sources"] or []
                        yield f"data: {json.dumps({'type': 'sources', 'sources': data['sources']})}\n\n"

                    elif current_event == "error" and "error" in data:
                        yield f"data: {json.dumps({'type': 'error', 'content': data['error']})}\n\n"

                    elif current_event == "done" and data.get("status") == "complete":
                        done_meta = data.get("meta") or None

    except httpx.HTTPStatusError as exc:
        response_body = ""
        try:
            response_body = (await exc.response.aread()).decode("utf-8", errors="ignore")[:1000]
        except Exception:
            response_body = ""
        logger.error(
            "RAG pipeline returned error",
            exc_info=True,
            extra={
                "status": exc.response.status_code,
                "url": f"{settings.rag_pipeline_url}/query",
                "response_body": response_body,
            },
        )
        yield f"data: {json.dumps({'type': 'error', 'content': 'The RAG pipeline returned an error. Please try again.'})}\n\n"

    except Exception as exc:
        logger.error(
            "RAG query failed",
            exc_info=True,
            extra={"url": f"{settings.rag_pipeline_url}/query"},
        )
        yield f"data: {json.dumps({'type': 'error', 'content': 'An internal error occurred. Please try again.'})}\n\n"
    finally:
        if owns_http_client:
            await client.aclose()

    # Yield the collected text as a special internal event
    full_text = _coerce_visible_answer_text("".join(collected_tokens))
    message_metadata = await build_enriched_assistant_message_metadata(
        question=message,
        answer_text=full_text,
        sources=latest_sources,
        upstream_meta=done_meta,
        user_role=user_role,
        db_pool=db_pool,
    )
    yield f"data: {json.dumps({'type': 'done', 'fullText': full_text, 'responsePayload': message_metadata.get('responsePayload'), 'metadata': message_metadata, 'meta': done_meta})}\n\n"


# Keep legacy non-streaming version for backward compatibility
async def query_rag_pipeline(
    message: str,
    conversation_history: list,
    conversation_id: str,
    http_client: httpx.AsyncClient | None = None,
    db_pool: asyncpg.Pool | None = None,
    language: str = "en",
    user_role: str = "employee",
    reasoning_mode: str | None = None,
    session_scope_active: bool = False,
) -> dict[str, Any]:
    """
    Proxies the user's message to the rag-pipeline and returns the full response string.
    """
    payload = {
        "query": message,
        "conversation_id": conversation_id,
        "stream": True,
        "conversation_history": conversation_history or [],
        "user_role": user_role,
        "reasoning_mode": reasoning_mode,
        "session_scope_active": session_scope_active,
    }

    assistant_message = ""
    latest_sources: list[dict] = []
    current_event: str | None = None
    done_meta: dict[str, Any] | None = None

    owns_http_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=300.0)
    try:
        async with client.stream(
            "POST",
            f"{settings.rag_pipeline_url}/query",
            json=payload
            ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    continue
                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if current_event == "token" and "token" in chunk:
                    assistant_message += chunk["token"]
                elif current_event == "sources" and "sources" in chunk:
                    latest_sources = chunk["sources"] or []
                elif current_event == "done" and chunk.get("status") == "complete":
                    done_meta = chunk.get("meta") or None
                elif current_event == "error" and "error" in chunk:
                    assistant_message = chunk["error"]
    except httpx.HTTPStatusError as exc:
        response_body = ""
        try:
            response_body = (await exc.response.aread()).decode("utf-8", errors="ignore")[:1000]
        except Exception:
            response_body = ""
        logger.error(
            "RAG pipeline returned error",
            exc_info=True,
            extra={
                "status": exc.response.status_code,
                "url": f"{settings.rag_pipeline_url}/query",
                "response_body": response_body,
            },
        )
        raise HTTPException(status_code=502, detail="The RAG pipeline returned an error. Please try again.")
    except Exception as exc:
        logger.error(
            "RAG query failed",
            exc_info=True,
            extra={"url": f"{settings.rag_pipeline_url}/query"},
        )
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")
    finally:
        if owns_http_client:
            await client.aclose()

    full_text = _coerce_visible_answer_text(assistant_message)
    metadata = await build_enriched_assistant_message_metadata(
        question=message,
        answer_text=full_text,
        sources=latest_sources,
        upstream_meta=done_meta,
        user_role=user_role,
        db_pool=db_pool,
    )
    return {
        "fullText": full_text,
        "responsePayload": metadata.get("responsePayload"),
        "metadata": metadata,
    }
