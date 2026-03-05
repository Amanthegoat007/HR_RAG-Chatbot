"""
============================================================================
FILE: services/backend/app/models.py
PURPOSE: Combined Pydantic schemas for Auth, Chat, and Ingest APIs.
============================================================================
"""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, List, Optional, Dict

# --- Auth Models ---

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=200)

class TokenResponse(BaseModel):
    token_type: str = "bearer"
    expires_in: int
    role: str

class UserProfile(BaseModel):
    id: str
    email: str
    roles: List[str]
    groups: List[str]
    sub: str

# --- Conversation Models ---

class ConversationItem(BaseModel):
    id: str
    title: str
    updatedAt: datetime
    createdAt: datetime

class ConversationListResponse(BaseModel):
    conversations: List[ConversationItem]

class CreateConversationRequest(BaseModel):
    title: str = "New Chat"

class ConversationResponse(BaseModel):
    id: str
    title: str
    createdAt: str

# --- Message Models ---

class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    createdAt: datetime

class MessageListResponse(BaseModel):
    messages: List[MessageItem]

class SendMessageRequest(BaseModel):
    conversationId: str
    message: str = Field(..., min_length=1, max_length=10000)
    language: Optional[str] = "en"

class SendMessageResponse(BaseModel):
    userMessage: MessageItem
    assistantMessage: MessageItem

class DeleteMessageAfterRequest(BaseModel):
    messageId: str

# --- Document Models ---

class UploadResponse(BaseModel):
    document_id: str
    filename: str
    file_size_bytes: int
    status: str
    job_id: str
    message: str

class DocumentMetadata(BaseModel):
    id: str
    filename: str
    original_format: str
    status: str
    file_size_bytes: int
    page_count: Optional[int]
    chunk_count: int
    uploaded_by: str
    uploaded_at: datetime
    processed_at: Optional[datetime]
    error_message: Optional[str]
    metadata: Dict[str, Any] = {}

class DocumentListResponse(BaseModel):
    documents: List[DocumentMetadata]
    total: int

class DeleteResponse(BaseModel):
    document_id: str
    filename: str
    message: str
    vectors_deleted: int
    minio_deleted: bool

# --- Health Models ---

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: Dict[str, str]
