"""
parallel 和 join 节点 — 并行执行与汇合。

parallel: 标记并行分支开始，本身不执行任何 Agent
join: 等待所有并行分支完成，合并结果

并行分支的执行逻辑在 executor 中处理。
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_parallel(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行 parallel 节点。

    标记并行区域开始。实际的 fan-out 由 executor 处理。
    此节点记录审计事件并返回分支信息。

    Args:
        state: 工作流状态
        config: 节点配置（config.parallel_branches 定义分支）

    Returns:
        并行分支信息
    """
    branches = config.parallel_branches
    if not branches:
        return {"error": "parallel 节点缺少 parallel_branches 配置"}

    branch_labels = []
    for i, branch in enumerate(branches):
        label = f"branch_{i}"
        if branch:
            label = f"branch_{i}_{branch[0]}" if branch[0] else f"branch_{i}"
        branch_labels.append(label)

    state.add_audit_event("parallel_started", config.node_id, {
        "branchCount": len(branches),
        "branches": branch_labels,
    })

    return {
        "parallel_branches": branches,
        "branch_count": len(branches),
        "branch_labels": branch_labels,
    }


async def execute_join(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行 join 节点。

    标记并行区域结束。收集所有并行分支的结果。
    实际的 barrier 等待由 executor 处理。

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        合并后的结果
    """
    # 收集所有 Agent 的输出作为合并结果
    agent_outputs = state.agent_outputs or {}
    merged_findings = []
    merged_evidence_refs = []

    for agent_name, output in agent_outputs.items():
        if isinstance(output, dict):
            merged_findings.append(f"[{agent_name}] {output.get('summary', '')}")
            refs = output.get("evidenceRefs", [])
            if isinstance(refs, list):
                merged_evidence_refs.extend(refs)

    state.add_audit_event("join_completed", config.node_id, {
        "agentCount": len(agent_outputs),
        "findingCount": len(merged_findings),
        "evidenceRefCount": len(merged_evidence_refs),
    })

    return {
        "merged_findings": merged_findings,
        "merged_evidence_refs": merged_evidence_refs,
        "agent_count": len(agent_outputs),
    }
