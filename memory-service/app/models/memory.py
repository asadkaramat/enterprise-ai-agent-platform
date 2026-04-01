from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class MessageItem(BaseModel):
    role: str
    content: str
    timestamp: str


class AppendMessageRequest(BaseModel):
    session_id: str
    role: str
    content: str


class StoreMemoryRequest(BaseModel):
    session_id: str
    agent_id: str
    content: str
    metadata: Optional[Dict[str, Any]] = {}


class RetrieveRequest(BaseModel):
    session_id: str
    query: str
    top_k: Optional[int] = 5


class MemoryItem(BaseModel):
    content: str
    score: float
    session_id: str
    timestamp: str


class RetrieveResponse(BaseModel):
    memories: List[MemoryItem]


class SessionEndRequest(BaseModel):
    session_id: str
    agent_id: str
