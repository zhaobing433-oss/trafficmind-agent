"""
rule_router 节点 — 规则路由。

根据事件类型和风险特征确定：
  - 是否需要人工审批
  - 调度优先级
  - 后续分支路径选择

不调用 LLM，完全确定性。
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_rule_router(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行规则路由。

    基于事件类型、风险等级、路段特征做确定性路由决策。

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        路由决策结果（route, priority, requiresApproval）
    """
    event = state.current_event or {}

    event_type = event.get("eventType", "")
    event_type_cn = event.get("eventTypeCn", "")
    is_main_road = event.get("isMainRoad", False)
    nearby_school = event.get("nearbySchool", False)
    nearby_hospital = event.get("nearbyHospital", False)
    # 如果 risk_assessment 尚未设置，先计算风险评分
    if not state.risk_assessment or not state.risk_assessment.get("riskScore"):
        try:
            from backend.tools.risk_tools import calculate_risk_score
            risk_result = calculate_risk_score(event)
            state.risk_assessment = risk_result
        except Exception:
            state.risk_assessment = {"riskScore": 0, "riskLevel": "低风险", "riskReasons": []}

    risk_level = state.risk_assessment.get("riskLevel", "未知")
    risk_score = state.risk_assessment.get("riskScore", 0)

    # 确定处置路线
    route = "standard"
    reason_parts = []

    # 高风险事件 → escalated
    if risk_level in ("高风险", "重大风险") or risk_score >= 61:
        route = "escalated"
        reason_parts.append(f"风险等级={risk_level}，需升级处置")

    # 学校/医院周边 → safety_priority
    if nearby_school or nearby_hospital:
        route = "safety_priority"
        nearby = []
        if nearby_school:
            nearby.append("学校")
        if nearby_hospital:
            nearby.append("医院")
        reason_parts.append(f"邻近{'/'.join(nearby)}，安全优先")

    # 主干道 → main_road
    if is_main_road and route == "standard":
        route = "main_road"
        reason_parts.append("主干道事件，影响范围广")

    # 确定优先级
    if risk_score >= 81:
        priority = "critical"
    elif risk_score >= 61:
        priority = "high"
    elif risk_score >= 31:
        priority = "medium"
    else:
        priority = "low"

    # 确定是否需要人工审批
    requires_approval = (
        risk_level in ("高风险", "重大风险")
        or (nearby_school and risk_score >= 31)
        or (nearby_hospital and risk_score >= 61)
    )

    result = {
        "route": route,
        "priority": priority,
        "requires_approval": requires_approval,
        "routing_reason": "；".join(reason_parts) if reason_parts else "常规处置流程",
        "event_type_cn": event_type_cn,
        "risk_level": risk_level,
    }

    state.add_audit_event("rule_routed", config.node_id, {
        "route": route,
        "priority": priority,
        "requiresApproval": requires_approval,
    })

    return result
