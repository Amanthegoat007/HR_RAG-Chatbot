from fastapi import APIRouter, Depends, Request, HTTPException
from starlette.responses import StreamingResponse
import asyncpg
import json
from typing import List
from datetime import datetime, timezone

from app.models import MessageItem, MessageListResponse, SendMessageRequest, SendMessageResponse
from app.dependencies import require_auth
from app import db
from app.services.query_proxy import query_rag_pipeline, stream_rag_pipeline

router = APIRouter()


async def _verify_conversation_ownership(pool: asyncpg.Pool, conversation_id: str, user_id: str):
    """Verify the user owns the conversation. Raises 404 if not found or unauthorized."""
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE id = $1::uuid AND user_id = $2",
            conversation_id, user_id
        )
    if not exists:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/{conversation_id}", response_model=MessageListResponse)
async def get_messages(conversation_id: str, request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool

    # IDOR protection: verify user owns this conversation
    await _verify_conversation_ownership(pool, conversation_id, user_id)
    
    messages = await db.fetch_messages(pool, conversation_id)
    
    items = []
    for m in messages:
        items.append(MessageItem(
            id=str(m["id"]),
            role=m["role"],
            content=m["content"],
            createdAt=m["created_at"]
        ))
        
    return MessageListResponse(messages=items)

@router.post("", response_model=SendMessageResponse)
async def send_message(req: SendMessageRequest, request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool

    # IDOR protection: verify user owns this conversation
    await _verify_conversation_ownership(pool, req.conversationId, user_id)
    
    # 1. Save user message
    user_msg_id = await db.create_message(pool, req.conversationId, "user", req.message)
    
    # 2. Fetch conversation history for multi-turn context
    history_rows = await db.fetch_messages(pool, req.conversationId)
    conversation_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history_rows[-10:]  # Last 10 messages for context window management
    ]
    
    # 3. Call RAG pipeline with conversation history
    assistant_content = await query_rag_pipeline(req.message, conversation_history)
    
    # 4. Save assistant message
    asst_msg_id = await db.create_message(pool, req.conversationId, "assistant", assistant_content)
    
    now = datetime.now(timezone.utc)
    # Return response
    return SendMessageResponse(
        userMessage=MessageItem(
            id=user_msg_id, role="user", content=req.message, createdAt=now
        ),
        assistantMessage=MessageItem(
            id=asst_msg_id, role="assistant", content=assistant_content, createdAt=now
        )
    )

@router.post("/stream")
async def stream_message(req: SendMessageRequest, request: Request, payload: dict = Depends(require_auth)):
    """Stream SSE tokens from the RAG pipeline directly to the frontend."""
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool

    # IDOR protection
    await _verify_conversation_ownership(pool, req.conversationId, user_id)

    # 1. Save user message immediately
    user_msg_id = await db.create_message(pool, req.conversationId, "user", req.message)

    # 2. Fetch conversation history
    history_rows = await db.fetch_messages(pool, req.conversationId)
    conversation_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history_rows[-10:]
    ]

    async def event_generator():
        """Wrap the stream_rag_pipeline generator and save the assistant message at the end."""
        # First, send the user message ID so frontend can update its optimistic message
        yield f"data: {json.dumps({'type': 'meta', 'userMessageId': user_msg_id})}\n\n"

        full_text = ""
        sources_json = ""
        async for event in stream_rag_pipeline(req.message, conversation_history):
            # Parse the event to check for the done event containing fullText
            if event.startswith("data: "):
                try:
                    data = json.loads(event[6:].strip())
                    if data.get("type") == "done":
                        full_text = data.get("fullText", "")
                    elif data.get("type") == "sources":
                        sources_json = json.dumps(data.get("sources", []))
                except json.JSONDecodeError:
                    pass
            yield event

        # 3. Save assistant message to DB after stream completes
        # Embed sources as hidden metadata so they persist across page refreshes
        save_text = full_text
        if sources_json and sources_json != "[]":
            save_text = f"{full_text}\n<!-- SOURCES_JSON:{sources_json} -->"

        if save_text:
            asst_msg_id = await db.create_message(pool, req.conversationId, "assistant", save_text)
            # Send the assistant message ID so frontend can update its state
            yield f"data: {json.dumps({'type': 'saved', 'assistantMessageId': asst_msg_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stop")
async def stop_message(payload: dict = Depends(require_auth)):
    # Currently a no-op since proxy aggregates sync, but allows frontend not to crash
    return {"message": "Streaming stopped"}

@router.delete("/{conversation_id}/{message_id}/after")
async def delete_messages_after(conversation_id: str, message_id: str, request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool

    # IDOR protection: verify user owns this conversation
    await _verify_conversation_ownership(pool, conversation_id, user_id)

    await db.delete_messages_after(pool, conversation_id, message_id)
    return {"message": "Messages deleted"}
