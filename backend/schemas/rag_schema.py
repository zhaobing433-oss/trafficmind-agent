"""RAG 相关 Schema"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List


class SearchResult(BaseModel):
    """语义检索单条结果"""
    content: str = ""
    docType: str = ""
    eventId: str = ""
    eventType: str = ""
    roadName: str = ""
    riskLevel: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class SearchResponse(BaseModel):
    """语义检索响应"""
    query: str = ""
    results: List[SearchResult] = Field(default_factory=list)
    error: str = ""


class AskResponse(BaseModel):
    """RAG 问答响应"""
    question: str = ""
    answer: str = ""
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    usedLLM: bool = False
