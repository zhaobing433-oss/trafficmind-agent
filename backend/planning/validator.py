"""
Plan Validator — Phase 17 Round 1

fail-closed 计划校验。Planner 输出不得直接执行，必须先过 validator。

materialize / run 要求 zero ERROR issues。

校验项：
  - stepId 唯一
  - dependency 存在
  - DAG 无环
  - 入口存在 + 全部可达
  - 至少一条 terminal 路径（可达 CLOSE）
  - step 数有界
  - stepType 合法（VALID_PLAN_STEP_TYPES）
  - agentType 合法
  - tool 已注册（unknown → ERROR，fail-closed）
  - risk 元数据与 ToolRegistry 一致
  - high-risk 步骤 approvalRequired=True（禁止 ToolPolicy bypass）
  - 同 actionType 双 high-risk instance → ERROR
  - 每个 high-risk action 有独立 approval gate（actionType 绑定）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.tool_registry import ToolRegistry, get_tool_registry
from backend.planning.models import (
    EXECUTABLE_AGENT_TYPES,
    MAX_PLAN_STEPS,
    VALID_PLAN_STEP_TYPES,
    IssueSeverity,
    Plan,
    PlanStep,
    ValidationIssue,
)
from backend.workflow.models import NodeType

# 合法 agentType：仅可执行领域 Agent。结构性/未实现 Agent 不得作为 agent_task 步骤（fail-closed）。
VALID_AGENT_TYPES = set(EXECUTABLE_AGENT_TYPES)


def _error(code: str, message: str, step_id: Optional[str] = None) -> ValidationIssue:
    return ValidationIssue(severity=IssueSeverity.ERROR, code=code, message=message, stepId=step_id)


def validate_plan(
    plan: Plan,
    tool_registry: Optional[ToolRegistry] = None,
) -> List[ValidationIssue]:
    """校验计划。返回问题列表，空 ERROR 列表表示合法。

    Args:
        plan: 待校验计划。
        tool_registry: 工具注册表（None 则用全局单例）。

    Returns:
        List[ValidationIssue]。materialize/run 要求无 ERROR 级别 issue。
    """
    registry = tool_registry or get_tool_registry()
    issues: List[ValidationIssue] = []
    steps = plan.steps

    # ── stepId 唯一 ──────────────────────────────────────────────
    seen_ids: Dict[str, str] = {}
    for s in steps:
        if s.stepId in seen_ids:
            issues.append(_error("duplicate_step_id", f"重复 stepId '{s.stepId}'", s.stepId))
        seen_ids[s.stepId] = s.stepId

    step_ids = {s.stepId for s in steps}

    # ── stepType 合法 ────────────────────────────────────────────
    for s in steps:
        if s.stepType not in VALID_PLAN_STEP_TYPES:
            issues.append(_error(
                "invalid_step_type",
                f"stepType '{s.stepType.value}' 不是合法的计划步骤类型",
                s.stepId,
            ))

    # ── dependency 存在 ──────────────────────────────────────────
    for s in steps:
        for dep in s.dependsOn:
            if dep not in step_ids:
                issues.append(_error(
                    "missing_dependency",
                    f"依赖的 stepId '{dep}' 不存在",
                    s.stepId,
                ))

    # ── DAG 无环 ────────────────────────────────────────────────
    # 构建后继邻接（dependsOn 反转）：succ[A] = {B | A ∈ B.dependsOn}
    succ: Dict[str, List[str]] = {s.stepId: [] for s in steps}
    for s in steps:
        for dep in s.dependsOn:
            if dep in step_ids:
                succ[dep].append(s.stepId)

    if _has_cycle(step_ids, succ):
        issues.append(_error("cyclic_dependency", "计划依赖存在环"))

    # ── 入口 + 可达性 ───────────────────────────────────────────
    entries = [s.stepId for s in steps if not s.dependsOn]
    if not entries:
        issues.append(_error("no_entry", "计划缺少入口步骤（无 dependsOn 为空 的步骤）"))

    reachable = _reachable(entries, succ)
    for s in steps:
        if s.stepId not in reachable:
            issues.append(_error("unreachable_step", "步骤不可达（孤儿步骤）", s.stepId))

    # ── terminal 路径（可达 CLOSE）──────────────────────────────
    close_steps = [s for s in steps if s.stepType == NodeType.CLOSE]
    if not close_steps:
        issues.append(_error("no_terminal_path", "计划缺少 CLOSE 终态步骤"))
    elif not any(s.stepId in reachable for s in close_steps):
        issues.append(_error("no_terminal_path", "CLOSE 步骤不可达，无 terminal 路径"))

    # ── step 数有界 ─────────────────────────────────────────────
    if len(steps) > MAX_PLAN_STEPS:
        issues.append(_error(
            "step_count_exceeded",
            f"步骤数 {len(steps)} 超过上限 {MAX_PLAN_STEPS}",
        ))

    # ── agentType 合法 ──────────────────────────────────────────
    for s in steps:
        if s.stepType == NodeType.AGENT_TASK:
            if not s.agentType:
                issues.append(_error("missing_agent_type", "AGENT_TASK 步骤缺少 agentType", s.stepId))
            elif s.agentType not in VALID_AGENT_TYPES:
                issues.append(_error(
                    "invalid_agent_type",
                    f"未知 agentType '{s.agentType}'",
                    s.stepId,
                ))

    # ── tool 注册 + risk 元数据一致 + high-risk 审批标注 ───────
    high_risk_actions: List[PlanStep] = []
    for s in steps:
        if s.stepType != NodeType.ACTION:
            continue
        action_type = s.actionType or s.toolName
        if not action_type:
            issues.append(_error("missing_action_type", "ACTION 步骤缺少 actionType", s.stepId))
            continue

        meta = registry.get(action_type)
        if meta is None:
            # unknown tool → ERROR（fail-closed）
            issues.append(_error(
                "unknown_tool",
                f"未注册工具 '{action_type}'，plan 非法（fail-closed）",
                s.stepId,
            ))
            continue

        # risk 元数据与 ToolRegistry 一致
        if s.riskLevel != meta.riskLevel.value:
            issues.append(_error(
                "risk_metadata_mismatch",
                f"riskLevel '{s.riskLevel}' 与 ToolRegistry 不一致（期望 '{meta.riskLevel.value}'）",
                s.stepId,
            ))

        # high-risk 必须 approvalRequired=True（禁止绕过 ToolPolicy）
        if meta.approvalRequired and not s.approvalRequired:
            issues.append(_error(
                "high_risk_missing_approval",
                f"高风险工具 '{action_type}' 必须标注 approvalRequired=True",
                s.stepId,
            ))

        if s.approvalRequired:
            high_risk_actions.append(s)

    # ── 同 actionType 双 high-risk instance → ERROR ────────────
    action_type_counts: Dict[str, int] = {}
    for s in high_risk_actions:
        at = s.actionType or s.toolName
        action_type_counts[at] = action_type_counts.get(at, 0) + 1
    for at, cnt in action_type_counts.items():
        if cnt > 1:
            issues.append(_error(
                "duplicate_high_risk_action_type",
                f"同一 plan 内存在 {cnt} 个同 actionType '{at}' 的 high-risk action（approval 为 actionType-scoped）",
            ))

    # ── 每个 high-risk action 有独立 approval gate ──────────────
    approval_steps = [s for s in steps if s.stepType == NodeType.HUMAN_APPROVAL]
    for act in high_risk_actions:
        at = act.actionType or act.toolName
        matching = [a for a in approval_steps if (a.actionType or a.toolName) == at]
        if not matching:
            issues.append(_error(
                "missing_approval_gate",
                f"high-risk action '{at}' 缺少独立 human_approval 门禁",
                act.stepId,
            ))
            continue
        # 该 approval 必须是 action 的直接前驱
        if not any(a.stepId in act.dependsOn for a in matching):
            issues.append(_error(
                "approval_not_predecessor",
                f"human_approval 未作为 action '{at}' 的直接前驱",
                act.stepId,
            ))

    return issues


def has_errors(issues: List[ValidationIssue]) -> bool:
    """是否包含 ERROR 级别 issue。"""
    return any(i.severity == IssueSeverity.ERROR for i in issues)


# ── 图算法 ──────────────────────────────────────────────────────


def _has_cycle(step_ids: set, succ: Dict[str, List[str]]) -> bool:
    """Kahn 拓扑排序检测环。"""
    indegree = {sid: 0 for sid in step_ids}
    for sid, children in succ.items():
        for c in children:
            indegree[c] = indegree.get(c, 0) + 1

    queue = [sid for sid, d in indegree.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for child in succ.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    return visited != len(step_ids)


def _reachable(entries: List[str], succ: Dict[str, List[str]]) -> set:
    """BFS 计算从入口可达的节点集合。"""
    reachable = set(entries)
    queue = list(entries)
    while queue:
        node = queue.pop(0)
        for child in succ.get(node, []):
            if child not in reachable:
                reachable.add(child)
                queue.append(child)
    return reachable
