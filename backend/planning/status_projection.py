"""
Status Projection — Phase 17 Round 1

runtime 状态 → PlanStepStatus（投影层）。

不修改原 NodeStatus / WorkflowRunStatus；只做只读投影。

DESIGN LOCK v1.1 AMENDMENT（Plan Step Audit Contract）：
  Plan step 的 canonical runtime audit source 复用现有 durable 记录：
    - workflow_node_runs（NodeStatus + output_snapshot）
    - workflow_action_records（ActionStatus / tool result）
    - workflow_events（node_started/node_completed/node_failed/tool_denied/approval_*）
    - workflow_approvals（decision）
  PlanStepStatus 由上述记录确定性派生（投影），不再重复生成
  plan_step_status_changed 事件（避免第二套状态机 / 重复事件状态）。
  该投影的输入全部来自 SQLite 持久层读取，进程重启后可完整重建。

映射（关键）：
  Node SUCCEEDED              → SUCCEEDED
  Node FAILED / Tool FAILURE  → FAILED
  Tool DENIED                 → DENIED
  approval required           → AWAITING_APPROVAL
  running                     → RUNNING
  pending + deps satisfied    → READY
  pending + deps incomplete   → PENDING
  upstream terminal non-success → BLOCKED
  cancelled                   → CANCELLED
  idempotent skip             → SKIPPED

BLOCKED 是 terminal（当前 plan revision 内不复活）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.planning.models import Plan, PlanStepStatus
from backend.workflow.models import NodeType

# 非成功 terminal 状态（触发下游 BLOCKED）
_NON_SUCCESS_TERMINAL = frozenset({
    PlanStepStatus.DENIED,
    PlanStepStatus.FAILED,
    PlanStepStatus.CANCELLED,
    PlanStepStatus.BLOCKED,
})

# Action 节点 output_snapshot.status → PlanStepStatus
_ACTION_OUTPUT_STATUS_MAP = {
    "denied": PlanStepStatus.DENIED,
    "approval_required": PlanStepStatus.AWAITING_APPROVAL,
    "failed": PlanStepStatus.FAILED,
    "skipped": PlanStepStatus.SKIPPED,
    "succeeded": PlanStepStatus.SUCCEEDED,
}


def _norm_node_run(nr: Any) -> Optional[Dict[str, Any]]:
    """WorkflowNodeRun / dict → dict。"""
    if nr is None:
        return None
    if isinstance(nr, dict):
        return nr
    if hasattr(nr, "to_dict"):
        return nr.to_dict()
    return None


def _project_action_output(output: Dict[str, Any], node_status: str) -> PlanStepStatus:
    """ACTION 节点：优先按 output_snapshot.status 判定（deny/approval_required/failed）。"""
    out_status = output.get("status") if isinstance(output, dict) else None
    if out_status and out_status in _ACTION_OUTPUT_STATUS_MAP:
        return _ACTION_OUTPUT_STATUS_MAP[out_status]
    # 兜底：按 node_run 状态
    return _node_status_map(node_status)


def _node_status_map(node_status: str) -> PlanStepStatus:
    """NodeStatus → PlanStepStatus（非 ACTION 节点）。"""
    if node_status == "succeeded":
        return PlanStepStatus.SUCCEEDED
    if node_status in ("failed", "timed_out"):
        return PlanStepStatus.FAILED
    if node_status == "running":
        return PlanStepStatus.RUNNING
    if node_status == "skipped":
        return PlanStepStatus.SKIPPED
    if node_status == "awaiting_approval":
        return PlanStepStatus.AWAITING_APPROVAL
    return PlanStepStatus.PENDING


def project_step_statuses(
    plan: Plan,
    node_runs: List[Any],
    run_status: str = "",
    pending_approval: Optional[Dict[str, Any]] = None,
) -> Dict[str, PlanStepStatus]:
    """投影每个 plan step 的执行状态。

    Args:
        plan: canonical 计划。
        node_runs: WorkflowNodeRun 列表（对象或 dict）。
        run_status: WorkflowRunStatus 字符串。
        pending_approval: 待审批信息（含 nodeId）。

    Returns:
        {stepId: PlanStepStatus}
    """
    # node_id → 最新 node_run（按 attempt 取最大）
    node_run_by_id: Dict[str, Dict[str, Any]] = {}
    for nr in node_runs:
        d = _norm_node_run(nr)
        if not d:
            continue
        node_id = d.get("nodeId", "")
        if not node_id:
            continue
        attempt = d.get("attempt", 0)
        existing = node_run_by_id.get(node_id)
        if existing is None or attempt >= existing.get("attempt", 0):
            node_run_by_id[node_id] = d

    pending_node_id = (pending_approval or {}).get("nodeId", "")

    # 先算已执行步骤的初始投影
    statuses: Dict[str, PlanStepStatus] = {}
    for s in plan.steps:
        nr = node_run_by_id.get(s.stepId)
        if nr is None:
            continue
        node_status = nr.get("status", "pending")
        if s.stepType == NodeType.ACTION:
            output = nr.get("outputSnapshot", {})
            statuses[s.stepId] = _project_action_output(output, node_status)
        else:
            statuses[s.stepId] = _node_status_map(node_status)

    # AWAITING_APPROVAL：pending 审批命中的 human_approval 步骤
    if run_status == "awaiting_approval" and pending_node_id:
        for s in plan.steps:
            if s.stepId == pending_node_id and s.stepType == NodeType.HUMAN_APPROVAL:
                statuses[s.stepId] = PlanStepStatus.AWAITING_APPROVAL

    # 未执行步骤：按依赖推导 PENDING / READY / BLOCKED / CANCELLED
    for s in plan.steps:
        if s.stepId in statuses:
            continue
        if run_status == "cancelled":
            statuses[s.stepId] = PlanStepStatus.CANCELLED
            continue

        # 上游是否有非成功 terminal
        blocked = any(
            statuses.get(dep, PlanStepStatus.PENDING) in _NON_SUCCESS_TERMINAL
            for dep in s.dependsOn
        )
        if blocked:
            statuses[s.stepId] = PlanStepStatus.BLOCKED
            continue

        # 依赖全部成功 → READY，否则 PENDING
        deps_ok = all(
            statuses.get(dep) == PlanStepStatus.SUCCEEDED
            for dep in s.dependsOn
        )
        statuses[s.stepId] = PlanStepStatus.READY if deps_ok else PlanStepStatus.PENDING

    return statuses
