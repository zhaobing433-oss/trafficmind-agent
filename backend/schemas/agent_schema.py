"""Agent 相关 Pydantic Schema — 结构化输出校验"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class AgentResult(BaseModel):
    """单 Agent 研判结果"""
    agentName: str = ""
    relevant: bool = False
    findings: List[str] = Field(default_factory=list)
    urgency: str = "low"
    suggestion: str = ""


class RoutedAnalyzeResponse(BaseModel):
    """动态路由多 Agent 研判响应"""
    eventSummary: Dict[str, Any] = Field(default_factory=dict)
    selectedAgents: List[str] = Field(default_factory=list)
    routingReasons: List[str] = Field(default_factory=list)
    skippedAgents: List[str] = Field(default_factory=list)
    agentResults: List[AgentResult] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    resolvedPlan: Dict[str, Any] = Field(default_factory=dict)
    finalDecision: str = ""
    dispatchPlan: Dict[str, Any] = Field(default_factory=dict)
    riskWarnings: List[str] = Field(default_factory=list)
    report: str = ""


class ConflictItem(BaseModel):
    """Agent 冲突条目"""
    type: str = ""
    description: str = ""
    agents: List[str] = Field(default_factory=list)
    severity: str = "low"
    resolution: str = ""


class RouteResult(BaseModel):
    """路由结果"""
    selectedAgents: List[str] = Field(default_factory=list)
    routingReasons: List[str] = Field(default_factory=list)
    skippedAgents: List[str] = Field(default_factory=list)
    riskTriggers: List[str] = Field(default_factory=list)


class ChainStep(BaseModel):
    """事件驱动链式协同步骤"""
    triggerAgent: str = ""
    triggerReason: str = ""
    targetAgent: str = ""
    result: Dict[str, Any] = Field(default_factory=dict)


class EventChainResult(BaseModel):
    """事件驱动链结果"""
    chain: List[ChainStep] = Field(default_factory=list)
    triggerReasons: List[str] = Field(default_factory=list)
    stepResults: List[Dict[str, Any]] = Field(default_factory=list)
    finalPlan: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


def safe_agent_result(data: Dict[str, Any]) -> AgentResult:
    """安全解析 AgentResult，缺失字段自动补默认值"""
    try:
        return AgentResult(**data)
    except Exception:
        return AgentResult(
            agentName=data.get("agentName", "Unknown"),
            findings=data.get("findings", []),
            urgency=data.get("urgency", "low"),
            suggestion=data.get("suggestion", ""),
        )
