"""
标准消息协议 — Phase 9.1
使用 Pydantic 定义所有 Agent 间通信消息类型。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agent.collaboration.roles import is_registered_agent

PROTOCOL_VERSION = "1.0"

VALID_MESSAGE_TYPES = {
    "task.assign", "task.started", "task.result", "task.failed",
    "tool.request", "tool.result",
    "conflict.detected", "arbitration.request", "arbitration.result",
    "fusion.request",
    "run.completed", "run.failed",
    "heartbeat",
}


class AgentMessage(BaseModel):
    """标准 Agent 通信消息。"""
    protocol_version: str = Field(default=PROTOCOL_VERSION, description="协议版本")
    message_id: str = Field(..., description="消息唯一 ID")
    run_id: str = Field(..., description="运行实例 ID")
    session_id: str = Field(..., description="会话 ID")
    trace_id: str = Field(default="", description="追踪 ID")
    task_id: str = Field(default="", description="任务 ID")
    parent_message_id: Optional[str] = Field(default=None, description="父消息 ID")
    sender: str = Field(..., description="发送方 Agent 名称")
    receiver: str = Field(..., description="接收方 Agent 名称")
    message_type: str = Field(..., description="消息类型")
    phase: str = Field(default="routing", description="执行阶段")
    priority: int = Field(default=5, ge=1, le=10, description="优先级 1-10")
    attempt: int = Field(default=1, ge=1, description="尝试次数")
    deadline: Optional[str] = Field(default=None, description="截止时间 ISO 格式")
    payload: Dict[str, Any] = Field(default_factory=dict, description="消息负载")
    context_refs: List[str] = Field(default_factory=list, description="引用的上下文 ID")
    evidence_refs: List[str] = Field(default_factory=list, description="引用的证据 ID")
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), description="创建时间")

    @field_validator("message_type")
    @classmethod
    def validate_message_type(cls, v: str) -> str:
        if v not in VALID_MESSAGE_TYPES:
            raise ValueError(f"非法 message_type '{v}'。合法值: {sorted(VALID_MESSAGE_TYPES)}")
        return v

    @field_validator("sender")
    @classmethod
    def validate_sender(cls, v: str) -> str:
        if not is_registered_agent(v):
            raise ValueError(f"发送方 '{v}' 未注册。已注册: Orchestrator + 各 Agent")
        return v

    @field_validator("receiver")
    @classmethod
    def validate_receiver(cls, v: str) -> str:
        if not is_registered_agent(v):
            raise ValueError(f"接收方 '{v}' 未注册。已注册: Orchestrator + 各 Agent")
        return v

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class AgentTask(BaseModel):
    """分配给 Agent 的任务。"""
    message_id: str
    task_id: str
    agent_name: str
    task_type: str = "analyze"
    input_fields: Dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[str] = None


class AgentResult(BaseModel):
    """Agent 返回的结构化结果。"""
    agent_name: str
    task_id: str
    status: str = Field(..., description="completed / partial / failed")
    findings: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")
    suggestion: str = ""
    urgency: str = "low"
    evidence_refs: List[Any] = Field(default_factory=list)
    proposed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    duration_ms: int = 0

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(f"confidence 必须在 [0, 1] 之间，当前值: {v}")
        return v


class ToolRequest(BaseModel):
    """工具调用请求。"""
    agent_name: str
    tool_name: str
    params: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具调用结果。"""
    agent_name: str
    tool_name: str
    result: Any = None
    success: bool = True
    error: Optional[str] = None


class ConflictRecord(BaseModel):
    """冲突记录。"""
    type: str
    description: str
    agents: List[str] = Field(default_factory=list)
    severity: str = "low"
    proposals: List[Dict[str, Any]] = Field(default_factory=list)


class ArbitrationResult(BaseModel):
    """仲裁结果。"""
    conflict_id: str
    resolved: bool = True
    resolution: str = ""
    reasoning: str = ""
    accepted_proposal: Optional[str] = None
    affected_agents: List[str] = Field(default_factory=list)
