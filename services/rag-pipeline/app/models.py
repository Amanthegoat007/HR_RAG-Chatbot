from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal

class QueryRequest(BaseModel):
    query: str = Field(..., description="The user's question or prompt")
    conversation_id: str = Field("new", description="Session ID for conversation history tracking")
    stream: bool = Field(True, description="Whether to stream the response via SSE")
    language: str = Field("en", description="Preferred response language")
    document_id: Optional[str] = Field(None, description="Optional document UUID to scope retrieval to a single document")
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list, description="Previous conversation turns for multi-turn context")
    user_role: str = Field("employee", description="Role of the user (e.g., admin, employee) to adjust response persona")
    reasoning_mode: Optional[Literal["fast", "deep"]] = Field(None, description="Optional reasoning mode override for the answer generation")
    
class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: Dict[str, str]
    models_loaded: bool
