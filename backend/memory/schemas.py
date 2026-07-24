"""
Memory V2 Pydantic 请求/响应模型 — Phase 10
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryItemSchema(BaseModel):
    """MemoryItem 的 Pydantic 响应模型。"""
    id: str
    memory_type: str
    scope_type: str = "session"
    scope_id: str = ""
    session_id: str = ""
    memory_key: str = ""
    value: Dict[str, Any] = Field(default_factory=dict)
    text_content: str = ""
    status: str = "candidate"
    confidence: float = 1.0
    authority_level: int = 0
    source_type: str = ""
    source_id: str = ""
    source_run_id: str = ""
    source_message_id: str = ""
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    supersedes_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_accessed_at: Optional[str] = None
    access_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class MemoryItemCreateRequest(BaseModel):
    """创建 MemoryItem 的请求模型。"""
    memory_type: str = Field(..., description="记忆类型")
    session_id: str = Field(..., description="会话 ID")
    memory_key: str = Field(default="", description="记忆键名")
    value: Dict[str, Any] = Field(default_factory=dict, description="记忆值")
    text_content: str = Field(default="", description="自然语言描述")
    status: str = Field(default="candidate", description="状态")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    authority_level: int = Field(default=0, description="权威等级")
    source_type: str = Field(default="", description="来源类型")
    source_id: str = Field(default="", description="来源标识")
    source_run_id: str = Field(default="", description="来源 Run ID")
    source_message_id: str = Field(default="", description="来源消息 ID")
    valid_from: Optional[str] = Field(default=None, description="生效时间")
    valid_until: Optional[str] = Field(default=None, description="失效时间")
    supersedes_id: str = Field(default="", description="取代的记忆 ID")
    scope_type: str = Field(default="session", description="作用域类型")
    scope_id: str = Field(default="", description="作用域 ID")

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type(cls, v: str) -> str:
        valid = {
            "session_goal", "stable_fact", "constraint",
            "confirmed_decision", "unresolved_issue", "user_correction",
            "run_summary", "proposal", "temporary_fact",
        }
        if v not in valid:
            raise ValueError(f"非法 memory_type '{v}'。合法值: {sorted(valid)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid = {"candidate", "active", "confirmed", "rejected", "superseded", "expired"}
        if v not in valid:
            raise ValueError(f"非法 status '{v}'。合法值: {sorted(valid)}")
        return v


class MemoryItemListResponse(BaseModel):
    """MemoryItem 列表响应。"""
    items: List[MemoryItemSchema] = Field(default_factory=list)
    total: int = 0
    session_id: str = ""


class MemoryTraceResponse(BaseModel):
    """MemoryTrace 响应模型。"""
    trace_id: str = ""
    run_id: str = ""
    session_id: str = ""
    recall_intent: str = ""
    recall_plan_json: str = "{}"
    candidates_json: str = "[]"
    selected_json: str = "[]"
    rejected_json: str = "[]"
    injection_map_json: str = "{}"
    write_candidates_json: str = "[]"
    write_results_json: str = "[]"
    token_estimate: int = 0
    recall_latency_ms: int = 0
    write_latency_ms: int = 0
    created_at: str = ""
    updated_at: str = ""

    model_config = ConfigDict(from_attributes=True)


class MemoryItemsBySessionRequest(BaseModel):
    """按 Session 查询记忆的请求。"""
    session_id: str = Field(..., description="会话 ID")
    memory_type: Optional[str] = Field(default=None, description="筛选记忆类型")
    memory_key: Optional[str] = Field(default=None, description="筛选记忆键名")
    status: Optional[str] = Field(default=None, description="筛选状态")
    limit: int = Field(default=50, ge=1, le=500)


class MemoryStatsResponse(BaseModel):
    """Session 记忆统计。"""
    session_id: str = ""
    total_items: int = 0
    active_items: int = 0
    confirmed_items: int = 0
    candidate_items: int = 0
    expired_items: int = 0
    rejected_items: int = 0
    superseded_items: int = 0
    by_type: Dict[str, int] = Field(default_factory=dict)
    trace_count: int = 0
