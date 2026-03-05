from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class QueryRequest(BaseModel):
    query: str = Field(..., description="The user's question or prompt")
    conversation_id: str = Field("new", description="Session ID for conversation history tracking")
    stream: bool = Field(True, description="Whether to stream the response via SSE")
    language: str = Field("en", description="Preferred response language")
    
class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: Dict[str, str]
    models_loaded: bool
