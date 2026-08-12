"""
risk_gate 节点 — 风险门控。

根据风险评估结果做条件分支：
  - 高风险 → 人工审批路径
  - 低/中风险 → 自动处置路径

节点的 condition 表达式决定路由结果。
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_risk_gate(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行风险门控。

    评估当前 risk_assessment 并返回路由决策。
    executor 根据 condition 表达式选择下一个节点。

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        门控决策（route, risk_level, requires_approval）
    """
    risk = state.risk_assessment or {}
    event = state.current_event or {}

    risk_score = risk.get("riskScore", 0)
    risk_level = risk.get("riskLevel", "低风险")
    is_main_road = event.get("isMainRoad", False)
    nearby_school = event.get("nearbySchool", False)
    nearby_hospital = event.get("nearbyHospital", False)

    # 决策逻辑
    requires_approval = False
    reasons = []

    if risk_level in ("高风险", "重大风险") or risk_score >= 61:
        requires_approval = True
        reasons.append(f"风险等级为{risk_level}（{risk_score}分）")

    if nearby_school and risk_score >= 31:
        requires_approval = True
        reasons.append("邻近学校，中风险及以上需审批")

    if nearby_hospital and risk_score >= 61:
        requires_approval = True
        reasons.append("邻近医院，高风险须审批")

    route = "approval" if requires_approval else "auto"
    gate_label = "进入人工审批" if requires_approval else "自动处置"

    result = {
        "route": route,
        "gate_label": gate_label,
        "requires_approval": requires_approval,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "reasons": reasons,
    }

    state.add_audit_event("risk_gate_evaluated", config.node_id, {
        "route": route,
        "riskScore": risk_score,
        "riskLevel": risk_level,
        "requiresApproval": requires_approval,
        "reasons": reasons,
    })

    return result
