from fastapi import APIRouter, Depends, Request, HTTPException
from starlette.responses import StreamingResponse
import asyncpg
import json
import asyncio
import httpx
import logging
from typing import List
from datetime import datetime, timezone

from app.models import MessageItem, MessageListResponse, SendMessageRequest, SendMessageResponse
from app.dependencies import require_auth
from app import db
from app.services.query_proxy import query_rag_pipeline, stream_rag_pipeline

logger = logging.getLogger(__name__)

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

async def _generate_and_save_title(pool: asyncpg.Pool, conversation_id: str, first_message: str):
    """Generates a concise title using the LLM and updates the conversation."""
    try:
        prompt = f"Generate a very concise, 3 to 5 word title for a conversation that starts with this message. Only return the title itself, no quotes, no conversational filler.\n\nMessage: {first_message}\n\nTitle:"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("http://llm:8080/v1/chat/completions", json={
                "model": "local",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 15,
                "temperature": 0.3,
                "skip_special_tokens": True,
                "chat_template_kwargs": {"enable_thinking": False},
            })
            if resp.status_code == 200:
                data = resp.json()
                title = data["choices"][0]["message"]["content"].strip().replace('"', '').replace("Title:", "").strip()
                if title:
                    async with pool.acquire() as conn:
                        await conn.execute("UPDATE conversations SET title = $1 WHERE id = $2::uuid", title, conversation_id)
    except Exception as e:
        logger.warning(f"Failed to generate conversation title: {e}")



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
            createdAt=m["created_at"],
            metadata=m.get("metadata") or {},
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
    
    # Check if this is the first message to trigger title generation
    history_rows = await db.fetch_messages(pool, req.conversationId)
    if len(history_rows) == 1:
        asyncio.create_task(_generate_and_save_title(pool, req.conversationId, req.message))
    
    # 2. Fetch conversation history for multi-turn context
    conversation_history = [
        {
            "role": m["role"],
            "content": m["content"],
            "metadata": m.get("metadata") or {},
        }
        for m in history_rows[-10:]  # Last 10 messages for context window management
    ]
    
    # Extract role mapping (admin/user)
    user_role = "admin" if user_id == "hr_admin" else "employee"

    # 3. Call RAG pipeline with conversation history
    assistant_result = await query_rag_pipeline(
        req.message, 
        conversation_history,
        req.conversationId,
        user_role=user_role,
        reasoning_mode=req.reasoningMode,
    )
    
    # 4. Save assistant message
    assistant_content = assistant_result["fullText"]
    assistant_metadata = assistant_result.get("metadata") or {}
    asst_msg_id = await db.create_message(
        pool,
        req.conversationId,
        "assistant",
        assistant_content,
        metadata=assistant_metadata,
    )
    
    now = datetime.now(timezone.utc)
    # Return response
    return SendMessageResponse(
        userMessage=MessageItem(
            id=user_msg_id, role="user", content=req.message, createdAt=now
        ),
        assistantMessage=MessageItem(
            id=asst_msg_id,
            role="assistant",
            content=assistant_content,
            createdAt=now,
            metadata=assistant_metadata,
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

    # Check if this is the first message to trigger title generation
    history_rows = await db.fetch_messages(pool, req.conversationId)
    if len(history_rows) == 1:
        asyncio.create_task(_generate_and_save_title(pool, req.conversationId, req.message))

    # 2. Fetch conversation history
    conversation_history = [
        {
            "role": m["role"],
            "content": m["content"],
            "metadata": m.get("metadata") or {},
        }
        for m in history_rows[-10:]
    ]

    async def event_generator():
        """Wrap the stream_rag_pipeline generator and save the assistant message at the end."""
        # First, send the user message ID so frontend can update its optimistic message
        yield f"data: {json.dumps({'type': 'meta', 'userMessageId': user_msg_id})}\n\n"

        full_text = ""
        assistant_metadata: dict = {}
        user_role = "admin" if user_id == "hr_admin" else "employee"
        
        async for event in stream_rag_pipeline(
            req.message, 
            conversation_history,
            req.conversationId,
            user_role=user_role,
            reasoning_mode=req.reasoningMode,
        ):
            # Parse the event to check for the done event containing fullText
            if event.startswith("data: "):
                try:
                    data = json.loads(event[6:].strip())
                    if data.get("type") == "done":
                        full_text = data.get("fullText", "")
                        assistant_metadata = data.get("metadata") or {}
                except json.JSONDecodeError:
                    pass
            yield event

        # 3. Save assistant message to DB after stream completes
        if full_text:
            asst_msg_id = await db.create_message(
                pool,
                req.conversationId,
                "assistant",
                full_text,
                metadata=assistant_metadata,
            )
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
