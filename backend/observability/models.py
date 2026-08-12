"""
Phase 14 Observability DTOs — 只读聚合，不修改状态。

安全约束：不含 chain_of_thought / thinking / hidden_reasoning / system_prompt。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NodeObservation:
    node_id: str = ""
    node_type: str = ""
    display_name: str = ""
    description: str = ""
    status: str = ""
    attempt: int = 0
    max_attempts: int = 1
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    input_summary: Dict[str, Any] = field(default_factory=dict)
    output_summary: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


@dataclass
class AgentObservation:
    agent_name: str = ""
    summary: str = ""
    urgency: str = ""
    findings: List[str] = field(default_factory=list)
    proposed_actions: List[Dict[str, Any]] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    spatial_context_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalObservation:
    approval_id: str = ""
    decision: str = ""
    reviewer: str = ""
    comment: str = ""
    created_at: str = ""
    decided_at: str = ""
    proposed_actions: List[Dict[str, Any]] = field(default_factory=list)
    edited_actions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ActionObservation:
    action_id: str = ""
    action_type: str = ""
    status: str = ""
    idempotency_key: str = ""
    before_snapshot_summary: Dict[str, Any] = field(default_factory=dict)
    after_snapshot_summary: Dict[str, Any] = field(default_factory=dict)
    improvement: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowObservability:
    run_id: str = ""
    definition_id: str = ""
    definition_name: str = ""
    status: str = ""
    started_at: str = ""
    completed_at: str = ""
    total_duration_ms: int = 0
    trigger_reason: str = ""
    current_node: str = ""
    nodes: List[NodeObservation] = field(default_factory=list)
    agent: Optional[AgentObservation] = None
    approval: Optional[ApprovalObservation] = None
    actions: List[ActionObservation] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    simulation_refs: Dict[str, Any] = field(default_factory=dict)


# ── Node display names ─────────────────────────────────────────────
NODE_DISPLAY: Dict[str, str] = {
    "trigger": "流程启动",
    "validate_event": "事件校验",
    "rule_router": "规则路由",
    "rag_retrieve": "知识检索",
    "memory_context": "历史上下文",
    "agent_task": "Agent 研判",
    "evidence_evaluate": "证据评估",
    "risk_gate": "风险门控",
    "human_approval": "人工审批",
    "action": "执行动作",
    "wait": "等待",
    "monitor": "效果监测",
    "close": "流程结束",
    "parallel": "并行执行",
    "join": "结果汇合",
}

NODE_DESCRIPTIONS: Dict[str, str] = {
    "trigger": "接收事件并启动工作流",
    "validate_event": "校验事件字段完整性和合法性",
    "rule_router": "根据事件类型和风险等级路由到对应的处置规则",
    "rag_retrieve": "从交通知识库检索相关规则、预案和历史案例",
    "memory_context": "加载历史记忆上下文，识别关联事件和已有决策",
    "agent_task": "Agent 分析事件上下文并生成处置建议",
    "evidence_evaluate": "评估 Agent 建议的证据充分性和置信度",
    "risk_gate": "根据风险评估决定是否需要人工审批",
    "human_approval": "人工审核 Agent 提议的处置动作",
    "action": "执行经审批的处置动作",
    "wait": "等待外部条件满足后继续",
    "monitor": "监测处置效果",
    "close": "工作流结束，记录最终状态",
}

# Sanitization: keys that must NEVER appear in observability output
FORBIDDEN_OBSERVABILITY_KEYS = {
    "chain_of_thought", "thinking", "hidden_reasoning",
    "system_prompt", "internal_state", "raw_llm_output",
    "cot", "reasoning_trace", "inner_monologue",
}


def sanitize_observability(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively remove forbidden keys from observability output."""
    if not isinstance(data, dict):
        return data
    result = {}
    for k, v in data.items():
        if k in FORBIDDEN_OBSERVABILITY_KEYS:
            continue
        if isinstance(v, dict):
            result[k] = sanitize_observability(v)
        elif isinstance(v, list):
            result[k] = [sanitize_observability(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result
