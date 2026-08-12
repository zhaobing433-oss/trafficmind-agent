"""
close 节点 — 工作流终止。

负责：
  - 标记 Workflow 为 completed
  - 汇总所有 Agent 输出
  - 生成最终决策摘要
  - 记录关闭审计事件

close 必须是每个 Workflow 的最后一个节点。
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState, WorkflowRunStatus


async def execute_close(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行关闭节点。

    汇总所有阶段输出并生成最终摘要。

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        最终结果摘要
    """
    # 汇总 Agent 输出
    agent_summaries = []
    agent_outputs = state.agent_outputs or {}
    for name, output in agent_outputs.items():
        if isinstance(output, dict) and output.get("summary"):
            agent_summaries.append(f"[{name}] {output['summary']}")

    # 汇总证据
    evidence_count = len(state.evidence_refs or [])

    # 汇总动作
    action_results = state.action_results or {}
    action_summary = []
    for action_type, result in action_results.items():
        if isinstance(result, dict):
            status = result.get("status", "unknown")
            error = result.get("error", "")
            action_summary.append(f"{action_type}: {status}" + (f" (错误: {error})" if error else ""))

    # 风险评估摘要
    risk = state.risk_assessment or {}
    risk_summary = f"风险等级: {risk.get('riskLevel', '未知')} ({risk.get('riskScore', 0)}分)"

    # 生成最终摘要
    final_summary_parts = [
        f"## Workflow 执行完成",
        f"**{risk_summary}**",
        f"",
        f"### Agent 分析结果",
    ]
    if agent_summaries:
        for s in agent_summaries:
            final_summary_parts.append(f"- {s}")
    else:
        final_summary_parts.append("- 无 Agent 输出")

    final_summary_parts.append(f"")
    final_summary_parts.append(f"### 证据引用: {evidence_count} 条")

    if action_summary:
        final_summary_parts.append(f"")
        final_summary_parts.append(f"### 外部动作")
        for a in action_summary:
            final_summary_parts.append(f"- {a}")

    final_summary = "\n".join(final_summary_parts)

    # 状态转换
    state.transition(WorkflowRunStatus.COMPLETED)

    # 审计事件
    state.add_audit_event("workflow_closed", config.node_id, {
        "agentCount": len(agent_outputs),
        "evidenceCount": evidence_count,
        "actionCount": len(action_results),
        "riskLevel": risk.get("riskLevel", ""),
    })

    result = {
        "workflow_status": "completed",
        "final_summary": final_summary,
        "agent_summaries": agent_summaries,
        "action_summary": action_summary,
        "risk_summary": risk_summary,
        "evidence_count": evidence_count,
        "rag_trace_ids": state.rag_trace_ids,
        "agent_run_ids": state.agent_run_ids,
        "approval_ids": state.approval_ids,
        "action_record_ids": state.action_record_ids,
        "error_count": len(state.errors or []),
    }

    return result
