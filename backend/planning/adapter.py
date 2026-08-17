"""
Dependency Adapter — Phase 17 Round 1

plan_to_definition(plan) -> WorkflowDefinition

严格依赖方向：
  B.dependsOn = [A]  →  A.next_nodes = [B]

先建 predecessor relation，再反转成 successor adjacency。

不新建 PlanExecutor：输出交给现有 DefinitionManager + WorkflowExecutor。

Approval Adapter：
  每个 high-risk ACTION 生成独立的 HUMAN_APPROVAL → ACTION 对；
  approval node 的 action_types = [该 actionType]，不把多个 high-risk action
  压进一个 approval node。

definition_id 直接绑定 planId（lineage identity），使
GET /planning/plans/{planId} 可 O(1) 反查 definition。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.planning.models import Plan, PlanDefinitionStatus, PlanStep
from backend.workflow.models import (
    DefinitionStatus,
    NodeConfig,
    NodeType,
    WorkflowDefinition,
)


def _max_attempts(step: PlanStep) -> int:
    """retryPolicy.maxRetries → max_attempts（默认 1）。"""
    max_retries = step.retryPolicy.get("maxRetries", 0)
    return max(1, int(max_retries) + 1)


def _node_config_for(step: PlanStep, agent_targets: List[str]) -> Dict[str, Any]:
    """根据 stepType 生成 NodeConfig.config。"""
    st = step.stepType
    if st == NodeType.VALIDATE_EVENT:
        return {"required_fields": ["eventType", "roadName"]}
    if st == NodeType.RULE_ROUTER:
        return {}
    if st == NodeType.RAG_RETRIEVE:
        return {"top_k": 5, "query_template": "{event_type} {road_name} 处置预案"}
    if st == NodeType.MEMORY_CONTEXT:
        return {"agent_targets": agent_targets}
    if st == NodeType.AGENT_TASK:
        return {"agent_name": step.agentType or ""}
    if st == NodeType.EVIDENCE_EVALUATE:
        return {"min_confidence": 0.3, "min_evidence_count": 1}
    if st == NodeType.RISK_GATE:
        return {}
    if st == NodeType.HUMAN_APPROVAL:
        # 每个 approval node 只声明其对应的 actionType（不压多个）
        return {"action_types": [step.actionType] if step.actionType else []}
    if st == NodeType.ACTION:
        return {"action_type": step.actionType or "", "action_params": {}}
    if st == NodeType.CLOSE:
        return {}
    return {}


def plan_to_definition(plan: Plan) -> WorkflowDefinition:
    """将 canonical Plan 映射为现有 WorkflowDefinition。

    Args:
        plan: canonical 计划。

    Returns:
        WorkflowDefinition（definition_id == planId）。
    """
    step_order = {s.stepId: i for i, s in enumerate(plan.steps)}

    # ── predecessor relation → successor adjacency ──────────────
    succ: Dict[str, List[str]] = {s.stepId: [] for s in plan.steps}
    for s in plan.steps:
        for dep in s.dependsOn:
            succ[dep].append(s.stepId)
    for k in succ:
        succ[k].sort(key=lambda sid: step_order.get(sid, 0))

    # 入口步骤（dependsOn 为空），按计划顺序
    entries = sorted(
        [s.stepId for s in plan.steps if not s.dependsOn],
        key=lambda sid: step_order.get(sid, 0),
    )

    agent_targets = [s.agentType for s in plan.steps if s.stepType == NodeType.AGENT_TASK and s.agentType]

    nodes: List[NodeConfig] = []

    # ── 生成 TRIGGER 入口（结构节点，非 PlanStep）──────────────
    nodes.append(NodeConfig(
        node_id="trigger",
        node_type=NodeType.TRIGGER,
        label="触发入口",
        description="接收事件，设置 current_event",
        next_nodes=list(entries),
        config={"initial_event": {}},
    ))

    # ── 每个 PlanStep → NodeConfig ─────────────────────────────
    for s in plan.steps:
        nodes.append(NodeConfig(
            node_id=s.stepId,
            node_type=s.stepType,
            label=s.objective or s.stepId,
            description=s.objective,
            config=_node_config_for(s, agent_targets),
            next_nodes=list(succ.get(s.stepId, [])),
            condition="requires_approval" if s.stepType == NodeType.RISK_GATE else None,
            timeout_seconds=s.timeoutSeconds,
            max_attempts=_max_attempts(s),
            retry_delay_seconds=5,
        ))

    definition_status = (
        DefinitionStatus.ACTIVE
        if plan.definitionStatus == PlanDefinitionStatus.ACTIVE
        else DefinitionStatus.DRAFT
    )

    return WorkflowDefinition(
        id=plan.planId,
        name=plan.goal or "自适应处置计划",
        description=f"确定性计划（{plan.goalType.value}），由 Adaptive Planning V1 生成",
        category=plan.goalType.value,
        status=definition_status,
        nodes=nodes,
        entry_node_id="trigger",
        metadata={
            "plan": plan.to_dict(),
            "planFingerprint": plan.planFingerprint,
            "definitionStatus": plan.definitionStatus.value,
            "version": plan.version,
        },
        created_at=plan.createdAt,
        updated_at=plan.updatedAt,
    )
