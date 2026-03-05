from fastapi import APIRouter, Depends, Request, HTTPException
import asyncpg
from typing import List
from datetime import datetime, timezone

from app.models import ConversationItem, ConversationListResponse, CreateConversationRequest, ConversationResponse
from app.dependencies import require_auth
from app import db

router = APIRouter()

@router.get("", response_model=ConversationListResponse)
async def get_conversations(request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool
    
    conversations = await db.list_conversations(pool, user_id)
    
    items = []
    for c in conversations:
        items.append(ConversationItem(
            id=str(c["id"]),
            title=c["title"],
            updatedAt=c["updated_at"],
            createdAt=c["updated_at"] # using updated_at as placeholder if created_at not queried
        ))
        
    return ConversationListResponse(conversations=items)

@router.post("", response_model=ConversationResponse)
async def create_conversation(req: CreateConversationRequest, request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool
    
    conv_id = await db.create_conversation(pool, user_id, req.title)
    
    return ConversationResponse(
        id=conv_id,
        title=req.title,
        createdAt=str(datetime.now(timezone.utc))
    )

@router.delete("")
async def delete_all_conversations(request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool
    
    deleted = await db.delete_all_conversations(pool, user_id)
    return {"message": f"Deleted {deleted} conversations"}

@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    pool: asyncpg.Pool = request.app.state.db_pool
    
    success = await db.delete_conversation(pool, conversation_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized")
        
    return {"message": "Conversation deleted"}
