"""
ActionCandidateResolver — Phase 17 Round 1

集中式确定性动作候选解析。规则不散落到 planner.py 中。

规则（Design Lock v1.1）：
  - notify:     riskLevel ∈ {高风险, 重大风险} → notify_wechat（HIGH_RISK）
  - simulation: 仅当存在仿真上下文且 goalType 匹配 → simulation_*（HIGH_RISK）
  - save_result: 闭环计划固定最后持久化（WRITE，幂等）

约束：
  - deterministic（无 LLM / 随机 / 网络）
  - 无 case_id hardcode（actionType 来自 ToolRegistry）
  - 不直接调用工具（只产出候选）
  - unknown/unregistered candidate 不进入 executable candidates，但产生
    ValidationIssue(ERROR)（不静默删除，validator 能看到问题）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.planning.context import PlanningContext
from backend.planning.models import GoalType, IssueSeverity, ValidationIssue

# 高风险阈值（与 config.HIGH_RISK_THRESHOLD 一致，但避免引入 config 依赖）
_HIGH_RISK_LEVELS = frozenset({"高风险", "重大风险"})


@dataclass
class ActionCandidate:
    """确定性动作候选。risk/approval 元数据来自 ToolRegistry。"""
    actionType: str
    toolName: str
    source: str
    riskLevel: str
    approvalRequired: bool
    reason: str
    paramsTemplate: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actionType": self.actionType,
            "toolName": self.toolName,
            "source": self.source,
            "riskLevel": self.riskLevel,
            "approvalRequired": self.approvalRequired,
            "reason": self.reason,
            "paramsTemplate": self.paramsTemplate,
        }


@dataclass
class ActionResolution:
    """动作候选解析结果。"""
    candidates: List[ActionCandidate] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)


class ActionCandidateResolver:
    """确定性动作候选解析器。"""

    def resolve(self, ctx: PlanningContext) -> ActionResolution:
        """根据上下文解析有序动作候选。

        Args:
            ctx: 计划上下文。

        Returns:
            ActionResolution（candidates + issues）。unknown tool 产生 ERROR issue
            且不进入 candidates。
        """
        candidates: List[ActionCandidate] = []
        issues: List[ValidationIssue] = []

        # Rule 1: notify（高风险）
        if ctx.risk_level in _HIGH_RISK_LEVELS:
            self._add_candidate(
                ctx, "notify_wechat", "rule_notify_high_risk",
                f"风险等级为「{ctx.risk_level}」，需要通知", candidates, issues,
            )

        # Rule 2: simulation（仅仿真上下文 / 仿真评估目标）
        if ctx.has_simulation_context() or ctx.goal_type_is(GoalType.SIMULATION_EVALUATION):
            sim_type = self._simulation_action_for(ctx)
            self._add_candidate(
                ctx, sim_type, "rule_simulation",
                "存在仿真上下文，需要仿真动作", candidates, issues,
            )

        # Rule 3: save_result（闭环持久化，固定最后）
        self._add_candidate(
            ctx, "save_result", "rule_persist_result",
            "闭环计划持久化分析结果", candidates, issues,
        )

        return ActionResolution(candidates=candidates, issues=issues)

    # ── 内部 ──────────────────────────────────────────────────────────

    def _add_candidate(
        self,
        ctx: PlanningContext,
        action_type: str,
        source: str,
        reason: str,
        candidates: List[ActionCandidate],
        issues: List[ValidationIssue],
    ) -> None:
        """将 action_type 解析为候选。unknown/unregistered → ERROR issue，不加入候选。"""
        meta = ctx.tool_registry.get(action_type)
        if meta is None:
            # 不静默删除：产生 ERROR，validator 会看到并拒绝 plan
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="unknown_tool",
                message=f"未注册工具 '{action_type}'，无法生成动作候选（fail-closed）",
                stepId=None,
            ))
            return

        candidates.append(ActionCandidate(
            actionType=action_type,
            toolName=action_type,
            source=source,
            riskLevel=meta.riskLevel.value,
            approvalRequired=meta.approvalRequired,
            reason=reason,
            paramsTemplate={},
        ))

    def _simulation_action_for(self, ctx: PlanningContext) -> str:
        """确定性选择仿真动作类型（Round1 占位：按 goalType 映射）。"""
        if ctx.goal_type_is(GoalType.SIGNAL_OPTIMIZATION):
            return "simulation_signal_adjustment"
        return "simulation_monitor"


def resolve_actions(ctx: PlanningContext) -> ActionResolution:
    """模块级便捷入口。"""
    return ActionCandidateResolver().resolve(ctx)
