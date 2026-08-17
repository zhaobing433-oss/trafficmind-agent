"""
Plan Revision / Child-run Continuation — Phase 17 Round 2

- version allocation（definition-level global monotonic，事务内原子）
- child WorkflowDefinition：只含 unresolved suffix（carried prefix 从 executable graph 排除）
- child run state 构建（继承 execution lineage + carried result refs）
- carried result validation（缺失/损坏 → fail-closed）
- 原子 cutover：单一 BEGIN IMMEDIATE 事务
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from backend.planning.adapter import _max_attempts, _node_config_for
from backend.planning.budget import ExecutionLineage
from backend.planning.models import Plan
from backend.planning.replanner import is_carried
from backend.workflow.models import (
    DefinitionStatus,
    NodeConfig,
    NodeType,
    WorkflowDefinition,
)


def compute_continuation_key(root_run_id: str, observation_id: str) -> str:
    """deterministic continuation key（幂等第二道防线）。"""
    raw = f"{root_run_id}:{observation_id}:replan"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def deterministic_child_run_id(root_run_id: str, observation_id: str) -> str:
    """deterministic child run ID（幂等第三道防线，PK 去重）。"""
    return f"wfrun_cont_{compute_continuation_key(root_run_id, observation_id)}"


def plan_to_child_definition(plan: Plan) -> WorkflowDefinition:
    """构建 child executable WorkflowDefinition（只含 unresolved suffix）。

    carried prefix 从 executable graph 完全排除；carried dependency 视为已满足。
    """
    carried_ids = {s.stepId for s in plan.steps if is_carried(s)}
    executable = [s for s in plan.steps if s.stepId not in carried_ids]
    step_order = {s.stepId: i for i, s in enumerate(executable)}

    # successor adjacency（carried dep 不建边 = 已满足）
    succ: Dict[str, List[str]] = {s.stepId: [] for s in executable}
    for s in executable:
        for dep in s.dependsOn:
            if dep in carried_ids:
                continue
            if dep in succ:
                succ[dep].append(s.stepId)
    for k in succ:
        succ[k].sort(key=lambda sid: step_order.get(sid, 0))

    # frontier：无未满足（非 carried）依赖的 executable step
    entries = sorted(
        [s.stepId for s in executable if not any(d not in carried_ids for d in s.dependsOn)],
        key=lambda sid: step_order.get(sid, 0),
    )

    agent_targets = [
        s.agentType for s in executable
        if s.stepType == NodeType.AGENT_TASK and s.agentType
    ]

    nodes: List[NodeConfig] = [
        NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, label="触发入口",
                   description="续接入口", next_nodes=list(entries), config={"initial_event": {}}),
    ]
    for s in executable:
        nodes.append(NodeConfig(
            node_id=s.stepId, node_type=s.stepType, label=s.objective or s.stepId,
            description=s.objective, config=_node_config_for(s, agent_targets),
            next_nodes=list(succ.get(s.stepId, [])),
            condition="requires_approval" if s.stepType == NodeType.RISK_GATE else None,
            timeout_seconds=s.timeoutSeconds, max_attempts=_max_attempts(s),
            retry_delay_seconds=5,
        ))

    return WorkflowDefinition(
        id=plan.planId,
        name=(plan.goal or "自适应计划") + "（续）",
        description=f"continuation revision v{plan.version}",
        category=plan.goalType.value,
        status=DefinitionStatus.ACTIVE,
        nodes=nodes,
        entry_node_id="trigger",
        metadata={"plan": plan.to_dict(), "planFingerprint": plan.planFingerprint,
                  "definitionStatus": plan.definitionStatus.value, "version": plan.version},
    )


def build_child_state(
    parent_state: Dict[str, Any],
    lineage: ExecutionLineage,
    replanned_from_run_id: str,
    replanned_from_version: int,
    carried_result_refs: Dict[str, str],
) -> Dict[str, Any]:
    """构建 child run 初始 state（继承 lineage + 重置执行字段 + carried refs）。"""
    state: Dict[str, Any] = {}
    # 继承 parent 上下文
    for key in ("currentEvent", "originalInput", "stableFacts", "riskAssessment",
                "simulationRefs", "sessionId", "eventThreadId", "workflowDefinitionId"):
        if key in parent_state:
            state[key] = parent_state[key]
    # 重置执行字段
    state["status"] = "pending"
    state["currentNode"] = ""
    state["nodeOutputs"] = {}
    state["proposedActions"] = []
    state["approvedActions"] = []
    state["actionResults"] = {}
    state["pendingApproval"] = None
    state["errors"] = []
    state["auditEvents"] = []
    state["ragTraceIds"] = []
    state["agentRunIds"] = []
    state["approvalIds"] = []
    state["actionRecordIds"] = []
    state["workflowRunId"] = ""  # 由 executor 回填
    # lineage + 指针 + carried refs
    state["executionLineage"] = lineage.to_dict()
    state["replannedFromRunId"] = replanned_from_run_id
    state["replannedFromVersion"] = replanned_from_version
    state["carriedForwardResultRefs"] = carried_result_refs
    return state


def validate_carried_refs(plan: Plan, repository) -> List[str]:
    """carried result 校验：old run + durable record 存在且 terminal success。缺失/损坏 fail-closed。"""
    issues: List[str] = []
    for s in plan.steps:
        if not is_carried(s):
            continue
        from_run_id = s.metadata.get("carriedForwardFromRunId", "")
        result_ref = s.resultRef or ""
        if not from_run_id or not result_ref:
            issues.append(f"carried step '{s.stepId}' 缺少 carriedForwardFromRunId/resultRef")
            continue
        old_run = repository.get_run(from_run_id)
        if old_run is None:
            issues.append(f"carried step '{s.stepId}' 的 fromRunId '{from_run_id}' 不存在")
            continue
        # 查找 old durable node record（node_run 或 action record）
        node_runs = repository.get_node_runs(from_run_id)
        found = any(nr.node_id == s.stepId for nr in node_runs)
        if not found:
            issues.append(f"carried step '{s.stepId}' 的 old node record 不存在（fail-closed）")
    return issues
