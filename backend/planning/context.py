"""
PlanningContext — Phase 17 Round 1

统一计划上下文。组合复用现有数据源（引用，不复制第二套数据源）：
  - normalize_event          → normalized_event（UNKNOWN 保留 None）
  - route_agents             → router_candidates
  - calculate_risk_score     → risk_context
  - ToolRegistry             → simulation_capabilities / tool_registry
  - RAG / Memory             → 由调用方预取（可选），空则空上下文

不变量：UNKNOWN != ZERO。None 仍是 None，空 evidence = []，不伪造 citation。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.agent.event_normalizer import normalize_event
from backend.agent.router import route_agents
from backend.agent.tool_registry import ToolRegistry, get_tool_registry
from backend.planning.models import GoalType
from backend.tools.risk_tools import calculate_risk_score


# canonical eventType（英文 code，config.EVENT_BASE_SCORES 的 key）→ GoalType
_GOAL_TYPE_BY_EVENT_TYPE = {
    "congestion": GoalType.CONGESTION_RESOLUTION,
    "accident": GoalType.ACCIDENT_RESPONSE,
    "signal_fault": GoalType.SIGNAL_OPTIMIZATION,
    "pedestrian_intrusion": GoalType.PEDESTRIAN_SAFETY,
    "wrong_way": GoalType.DISPATCH,
    "illegal_parking": GoalType.DISPATCH,
    "vehicle_stopped": GoalType.DISPATCH,
    "construction_block": GoalType.DISPATCH,
}

# display-only fallback（eventType 以中文传入时）—— 仅兜底，非核心规划依据
_GOAL_TYPE_BY_EVENT_CN = {
    "拥堵": GoalType.CONGESTION_RESOLUTION,
    "事故": GoalType.ACCIDENT_RESPONSE,
    "信号灯异常": GoalType.SIGNAL_OPTIMIZATION,
    "行人闯入": GoalType.PEDESTRIAN_SAFETY,
    "逆行": GoalType.DISPATCH,
    "违停": GoalType.DISPATCH,
    "车辆滞留": GoalType.DISPATCH,
    "施工占道": GoalType.DISPATCH,
}


def derive_goal_type(normalized_event: Dict[str, Any]) -> GoalType:
    """确定性派生计划目标类型。

    优先 canonical eventType（英文 code）；中文 eventTypeCn 仅作兜底（display）。
    仿真上下文最高优先。
    """
    if normalized_event.get("_simulation_refs") or normalized_event.get("simulationRunId"):
        return GoalType.SIMULATION_EVALUATION

    event_type = normalized_event.get("eventType", "")
    if event_type in _GOAL_TYPE_BY_EVENT_TYPE:
        return _GOAL_TYPE_BY_EVENT_TYPE[event_type]

    # 兜底：canonical code 未命中时，用 display 名（历史中文输入兼容）
    event_cn = normalized_event.get("eventTypeCn", "")
    if event_cn in _GOAL_TYPE_BY_EVENT_CN:
        return _GOAL_TYPE_BY_EVENT_CN[event_cn]

    return GoalType.GENERIC


@dataclass
class PlanningContext:
    """计划上下文（组合引用现有数据源）。"""
    user_goal: str
    normalized_event: Dict[str, Any]
    router_candidates: Dict[str, Any]
    risk_context: Dict[str, Any]
    tool_registry: ToolRegistry
    goal_type: GoalType = GoalType.GENERIC
    rag_evidence: Dict[str, Any] = field(default_factory=dict)
    memory_context: Dict[str, Any] = field(default_factory=dict)
    simulation_capabilities: List[Any] = field(default_factory=list)
    workflow_context: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)

    @property
    def risk_level(self) -> str:
        """风险等级（中文，如 低风险/中风险/高风险/重大风险）。"""
        return self.risk_context.get("riskLevel", "")

    @property
    def risk_score(self) -> int:
        """风险分数（0-100）。"""
        return self.risk_context.get("riskScore", 0)

    @property
    def selected_agents(self) -> List[str]:
        """路由选中的 Agent 列表。"""
        return self.router_candidates.get("selectedAgents", [])

    @property
    def requires_approval(self) -> bool:
        """是否高危需审批（风险等级 ∈ 高风险/重大风险）。"""
        return self.risk_level in ("高风险", "重大风险")

    def has_simulation_context(self) -> bool:
        """是否存在仿真上下文。"""
        ev = self.normalized_event or {}
        return bool(
            ev.get("_simulation_refs")
            or ev.get("simulationRunId")
            or ev.get("simulation_run_id")
        )

    def goal_type_is(self, goal_type: GoalType) -> bool:
        return self.goal_type == goal_type


def build_planning_context(
    raw_event: Dict[str, Any],
    user_goal: str = "",
    rag_evidence: Optional[Dict[str, Any]] = None,
    memory_context: Optional[Dict[str, Any]] = None,
    simulation_capabilities: Optional[List[Any]] = None,
    constraints: Optional[Dict[str, Any]] = None,
) -> PlanningContext:
    """组合现有数据源构建 PlanningContext。

    Args:
        raw_event: 原始事件（可能含 standardEvent 包装 / 未知字段）。
        user_goal: 用户目标文本。
        rag_evidence: 预取的 RAG 证据（可选）。
        memory_context: 预取的 Memory 上下文（可选）。
        simulation_capabilities: 仿真能力列表（默认取 ToolRegistry category=simulation）。
        constraints: 计划约束。

    Returns:
        PlanningContext（组合引用，不复制数据源）。
    """
    normalized = normalize_event(raw_event)

    # 风险评分（确定性）
    risk = calculate_risk_score(normalized)

    # 路由（确定性；注入 riskLevel 以便高风险触发 DispatchAgent）
    routing_input = dict(raw_event)
    routing_input.setdefault("riskLevel", risk.get("riskLevel", ""))
    routing_input.setdefault("riskScore", risk.get("riskScore", 0))
    routing = route_agents(routing_input)

    registry = get_tool_registry()
    if simulation_capabilities is None:
        simulation_capabilities = [
            m for m in registry.all() if m.category == "simulation"
        ]

    return PlanningContext(
        user_goal=user_goal,
        normalized_event=normalized,
        router_candidates=routing,
        risk_context=risk,
        tool_registry=registry,
        goal_type=derive_goal_type(normalized),
        rag_evidence=rag_evidence or {
            "query": "",
            "results": [],
            "resultCount": 0,
            "traceId": "",
            "degraded": False,
        },
        memory_context=memory_context or {},
        simulation_capabilities=simulation_capabilities or [],
        workflow_context={},
        constraints=constraints or {},
    )
