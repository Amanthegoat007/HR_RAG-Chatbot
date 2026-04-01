from fastapi import APIRouter, Depends, Request, HTTPException
from starlette.responses import StreamingResponse
import asyncpg
import json
import logging
from datetime import datetime, timezone

from app.models import MessageItem, MessageListResponse, SendMessageRequest, SendMessageResponse
from app.config import settings
from app.dependencies import require_auth
from app import db
from app.services.conversation_working_set import build_conversation_working_set
from app.services.query_proxy import query_rag_pipeline, stream_rag_pipeline
from app.maintenance import generate_conversation_title

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


def _enqueue_title_generation(conversation_id: str, first_message: str) -> None:
    try:
        generate_conversation_title.delay(conversation_id, first_message)
    except Exception as exc:
        logger.warning(
            "Failed to queue conversation title generation",
            extra={"conversation_id": conversation_id, "error": str(exc)},
        )

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
        _enqueue_title_generation(req.conversationId, req.message)
    
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
    user_role = "admin" if user_id == settings.admin_username else "employee"
    session_scope_active = await db.conversation_has_session_documents(pool, req.conversationId)
    conversation_working_set = await build_conversation_working_set(
        pool,
        req.conversationId,
        recent_messages=conversation_history,
        active_attachment_document_id=req.activeAttachmentDocumentId,
    )

    # 3. Call RAG pipeline with conversation history
    assistant_result = await query_rag_pipeline(
        req.message, 
        conversation_history,
        req.conversationId,
        http_client=request.app.state.http_client,
        db_pool=pool,
        user_role=user_role,
        reasoning_mode=req.reasoningMode,
        session_scope_active=session_scope_active,
        conversation_working_set=conversation_working_set,
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
        _enqueue_title_generation(req.conversationId, req.message)

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
        user_role = "admin" if user_id == settings.admin_username else "employee"
        session_scope_active = await db.conversation_has_session_documents(pool, req.conversationId)
        conversation_working_set = await build_conversation_working_set(
            pool,
            req.conversationId,
            recent_messages=conversation_history,
            active_attachment_document_id=req.activeAttachmentDocumentId,
        )
        
        async for event in stream_rag_pipeline(
            req.message, 
            conversation_history,
            req.conversationId,
            http_client=request.app.state.http_client,
            db_pool=pool,
            user_role=user_role,
            reasoning_mode=req.reasoningMode,
            session_scope_active=session_scope_active,
            conversation_working_set=conversation_working_set,
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
