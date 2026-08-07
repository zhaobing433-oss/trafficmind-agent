"""
human_approval 节点 — 人工审批。

执行时暂停 Workflow，创建审批记录，等待人工决策。

审批操作：
  - approve: 批准，继续执行后续 action 节点
  - reject: 驳回，Workflow 终止
  - edit_and_approve: 编辑后批准

未经批准不得执行外部 action 节点。
"""

from typing import Any, Dict

from backend.workflow.models import (
    ApprovalDecision,
    NodeConfig,
    generate_approval_id,
)
from backend.workflow.state import TrafficWorkflowState, WorkflowRunStatus


async def execute_human_approval(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行人工审批节点（第一阶段：创建审批，暂停 Workflow）。

    审批阶段：
      1. 本方法创建审批记录并暂停 Workflow
      2. 人工通过 API 调用 approve/reject/edit_and_approve
      3. executor.resume() 继续执行

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        审批信息（含 approval_id，供 API 调用）
    """
    # ── 恢复场景：若已批准/驳回，跳过审批节点 ──────────────────────
    if state.pending_approval is None and state.approved_actions:
        # 已批准：直接跳过，继续到下一个节点
        state.add_audit_event("approval_completed", config.node_id, {
            "status": "already_approved",
        })
        return {"approval_required": False, "status": "already_approved"}

    # 收集提议的动作
    proposed_actions = state.proposed_actions or []

    # 如果没有提议动作，从 Agent 输出和建议中构建
    if not proposed_actions:
        agent_outputs = state.agent_outputs or {}
        for name, output in agent_outputs.items():
            if isinstance(output, dict) and output.get("summary"):
                proposed_actions.append({
                    "source": name,
                    "action": output.get("summary", ""),
                    "urgency": output.get("urgency", "low"),
                    "evidenceRefs": output.get("evidenceRefs", []),
                })
        state.proposed_actions = proposed_actions

    # 从 rule_router 结果中获取审批原因
    risk = state.risk_assessment or {}
    event = state.current_event or {}

    # 创建审批记录
    approval_id = generate_approval_id()
    approval = {
        "approvalId": approval_id,
        "workflowRunId": state.workflow_run_id,
        "nodeId": config.node_id,
        "proposedActions": proposed_actions,
        "decision": ApprovalDecision.PENDING.value,
        "reviewer": "",
        "comment": "",
        "context": {
            "riskLevel": risk.get("riskLevel", "未知"),
            "riskScore": risk.get("riskScore", 0),
            "eventType": event.get("eventTypeCn", event.get("eventType", "")),
            "roadName": event.get("roadName", ""),
            "agentCount": len(state.agent_outputs or {}),
        },
    }

    # 更新 state
    state.pending_approval = approval
    state.approval_ids.append(approval_id)
    state.transition(WorkflowRunStatus.AWAITING_APPROVAL)

    state.add_audit_event("approval_required", config.node_id, {
        "approvalId": approval_id,
        "actionCount": len(proposed_actions),
        "riskLevel": risk.get("riskLevel", ""),
    })

    return {
        "approval_required": True,
        "approval_id": approval_id,
        "proposed_actions": proposed_actions,
        "pause_reason": "需要人工审批",
    }


def process_approval_decision(
    state: TrafficWorkflowState,
    decision: ApprovalDecision,
    edited_actions: list = None,
    reviewer: str = "",
    comment: str = "",
) -> Dict[str, Any]:
    """处理审批决策（由 API 调用触发，非节点执行）。

    Args:
        state: 工作流状态
        decision: 审批决策
        edited_actions: 编辑后的动作（edit_and_approve 时）
        reviewer: 审批人
        comment: 审批意见

    Returns:
        处理结果
    """
    pending = state.pending_approval
    if not pending:
        return {"error": "没有待处理的审批"}

    approval_id = pending.get("approvalId", "")

    if decision == ApprovalDecision.APPROVED:
        state.approved_actions = pending.get("proposedActions", [])
        state.add_audit_event("approval_approved", pending.get("nodeId", ""), {
            "approvalId": approval_id,
            "reviewer": reviewer,
            "comment": comment,
        })
        result = {"decision": "approved", "approved_actions": state.approved_actions}

    elif decision == ApprovalDecision.REJECTED:
        state.approved_actions = []
        state.transition(WorkflowRunStatus.REJECTED)
        state.add_audit_event("approval_rejected", pending.get("nodeId", ""), {
            "approvalId": approval_id,
            "reviewer": reviewer,
            "comment": comment,
        })
        result = {"decision": "rejected", "reason": comment or "审批人驳回"}

    elif decision == ApprovalDecision.EDITED:
        state.approved_actions = edited_actions or pending.get("proposedActions", [])
        state.add_audit_event("approval_edited", pending.get("nodeId", ""), {
            "approvalId": approval_id,
            "reviewer": reviewer,
            "comment": comment,
            "editedActionCount": len(edited_actions or []),
        })
        result = {"decision": "edited_and_approved", "approved_actions": state.approved_actions}

    else:
        return {"error": f"未知的审批决策: {decision}"}

    state.pending_approval = None
    return result
