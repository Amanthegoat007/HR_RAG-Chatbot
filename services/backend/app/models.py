"""
============================================================================
FILE: services/backend/app/models.py
PURPOSE: Combined Pydantic schemas for Auth, Chat, and Ingest APIs.
============================================================================
"""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, List, Optional, Dict, Literal

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
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MessageListResponse(BaseModel):
    messages: List[MessageItem]

class SendMessageRequest(BaseModel):
    conversationId: str
    message: str = Field(..., min_length=1, max_length=10000)
    language: Optional[str] = "en"
    reasoningMode: Optional[Literal["fast", "deep"]] = None
    activeAttachmentDocumentId: Optional[str] = None

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
    scope: Literal["library", "session"] = "library"
    conversation_id: Optional[str] = None

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
    scope: Literal["library", "session"] = "library"
    conversation_id: Optional[str] = None

class DocumentListResponse(BaseModel):
    documents: List[DocumentMetadata]
    total: int

class DeleteResponse(BaseModel):
    document_id: str
    filename: str
    message: str
    vectors_deleted: int
    minio_deleted: bool


# --- Benchmark Models ---

BenchmarkPreset = Literal[
    "smoke-1",
    "smoke-5",
    "smoke-10",
    "smoke-20",
    "smoke-30",
    "smoke-custom",
]

class BenchmarkRunRequest(BaseModel):
    preset: BenchmarkPreset
    concurrency: Optional[int] = Field(default=None, ge=1, le=30)


class BenchmarkMonitoringLinks(BaseModel):
    grafanaUrl: str
    prometheusUrl: str


class BenchmarkTierSummary(BaseModel):
    concurrency: int
    totalRequests: int
    successRate: float
    ttftP95Seconds: Optional[float] = None
    totalP95Seconds: Optional[float] = None
    throughputRps: float
    tierStartedAtUtc: Optional[str] = None
    tierFinishedAtUtc: Optional[str] = None
    topErrors: List[Dict[str, Any]] = Field(default_factory=list)


class BenchmarkRunStatusResponse(BaseModel):
    jobId: str
    preset: BenchmarkPreset
    requestedConcurrency: Optional[int] = None
    status: Literal["queued", "running", "succeeded", "failed"]
    queuedAtUtc: str
    startedAtUtc: Optional[str] = None
    finishedAtUtc: Optional[str] = None
    summary: Optional[BenchmarkTierSummary] = None
    error: Optional[str] = None
    summaryPath: Optional[str] = None
    resultsPath: Optional[str] = None


class BenchmarkBootstrapResponse(BaseModel):
    monitoring: BenchmarkMonitoringLinks
    canRun: bool
    activeRun: Optional[BenchmarkRunStatusResponse] = None
    latestRun: Optional[BenchmarkRunStatusResponse] = None


class BenchmarkRunCreatedResponse(BaseModel):
    jobId: str
    status: Literal["queued", "running"]

# --- Health Models ---

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: Dict[str, str]
