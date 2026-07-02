"""ReAct 诊断 Agent Schema"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class ReActStep(BaseModel):
    """ReAct 单步"""
    step: int = 1
    thought: str = ""
    action: str = ""
    actionInput: Dict[str, Any] = Field(default_factory=dict)
    observation: str = ""
    error: Optional[str] = None


class ToolCall(BaseModel):
    """工具调用记录"""
    tool: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    success: bool = True
    error: Optional[str] = None


class ReactDiagnoseResponse(BaseModel):
    """受控 ReAct 诊断响应"""
    question: str = ""
    steps: List[ReActStep] = Field(default_factory=list)
    toolCalls: List[ToolCall] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    finalAnswer: str = ""
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = Field(default_factory=list)
    usedLLM: bool = False


def safe_react_response(data: Dict[str, Any]) -> ReactDiagnoseResponse:
    """安全解析 ReAct 响应"""
    try:
        return ReactDiagnoseResponse(**data)
    except Exception:
        return ReactDiagnoseResponse(
            question=data.get("question", ""),
            finalAnswer=data.get("finalAnswer", "无法生成诊断回答"),
            warnings=["[Schema] 响应格式校验失败，已使用默认值"],
            usedLLM=data.get("usedLLM", False),
        )
