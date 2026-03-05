import httpx
import logging
import json
from typing import AsyncGenerator

from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


async def stream_rag_pipeline(
    message: str,
    conversation_history: list,
    language: str = "en"
) -> AsyncGenerator[str, None]:
    """
    Proxy SSE events from the rag-pipeline to the client.
    Yields raw SSE-formatted strings that can be sent directly via StreamingResponse.

    Also yields a special internal event '__final__' at the end with the collected
    assistant text, so the caller can save it to the database.
    """
    payload = {
        "query": message,
        "conversation_id": "temp",
        "stream": True
    }

    collected_tokens: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
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
                        event_type = line.split(":", 1)[1].strip()
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
                        if "token" in data:
                            collected_tokens.append(data["token"])
                            yield f"data: {json.dumps({'type': 'token', 'content': data['token']})}\n\n"

                        elif "stage" in data:
                            yield f"data: {json.dumps({'type': 'stage', 'stage': data['stage'], 'label': data.get('label', ''), 'status': data.get('status', 'active')})}\n\n"

                        elif "sources" in data:
                            yield f"data: {json.dumps({'type': 'sources', 'sources': data['sources']})}\n\n"

                        elif "error" in data:
                            yield f"data: {json.dumps({'type': 'error', 'content': data['error']})}\n\n"

                        elif "status" in data and data["status"] == "complete":
                            pass  # Will send done below

    except httpx.HTTPStatusError as exc:
        logger.error("RAG pipeline returned error", exc_info=True, extra={"status": exc.response.status_code})
        yield f"data: {json.dumps({'type': 'error', 'content': 'The RAG pipeline returned an error. Please try again.'})}\n\n"

    except Exception as exc:
        logger.error("RAG query failed", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'content': 'An internal error occurred. Please try again.'})}\n\n"

    # Yield the collected text as a special internal event
    full_text = "".join(collected_tokens)
    yield f"data: {json.dumps({'type': 'done', 'fullText': full_text})}\n\n"


# Keep legacy non-streaming version for backward compatibility
async def query_rag_pipeline(
    message: str,
    conversation_history: list,
    language: str = "en"
) -> str:
    """
    Proxies the user's message to the rag-pipeline and returns the full response string.
    """
    payload = {
        "query": message,
        "conversation_id": "temp",
        "stream": True
    }

    assistant_message = ""

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{settings.rag_pipeline_url}/query",
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            if "token" in chunk:
                                assistant_message += chunk["token"]
                            elif "error" in chunk:
                                assistant_message = chunk["error"]
                        except json.JSONDecodeError:
                            pass
    except httpx.HTTPStatusError as exc:
        logger.error("RAG pipeline returned error", exc_info=True, extra={"status": exc.response.status_code})
        raise HTTPException(status_code=502, detail="The RAG pipeline returned an error. Please try again.")
    except Exception as exc:
        logger.error("RAG query failed", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

    return assistant_message
