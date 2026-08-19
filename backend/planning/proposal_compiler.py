"""
Deterministic Proposal Compiler — Phase 18 Round 1

proposal → canonical Plan（PURE / SYNC / DETERMINISTIC / NO DB / NO LLM / NO NETWORK / NO TOOL）。

流程：
  1. snapshot hash 校验（SNAPSHOT_MISMATCH）
  2. proposalStepId 唯一（已在 strict parser 校验，此处仅防御）
  3. dependency 校验（存在性）
  4. LINEAR-only 校验（UNSUPPORTED_PLAN_SHAPE）
  5. capability 解析（agent / action）
  6. parameterHints 归一化
  7. 生成 canonical stable stepId
  8. 插入 structural steps
  9. 内部派生 agentType / actionType
  10. 从 ToolRegistry 派生 riskLevel / approvalRequired
  11. 派生 retry / timeout
  12. Approval Identity V2 绑定
  13. 产出 canonical Plan
  14. 复用 validate_plan() fail-closed

任何 unsupported → fail closed（PlannerFailure）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.tool_registry import get_tool_registry
from backend.planning.capability_snapshot import (
    ACTION_CAPABILITY_MAP,
    AGENT_CAPABILITY_MAP,
    PlannerCapabilitySnapshot,
)
from backend.planning.context import PlanningContext
from backend.planning.models import (
    Plan,
    PlanDefinitionStatus,
    PlanningMode,
    PlanStep,
    compute_fingerprint,
    generate_plan_id,
)
from backend.planning.param_schema import normalize_parameter_hints
from backend.planning.proposal import PlanProposal, PlanProposalStep, PlannerFailure, PlannerFailureCode
from backend.planning.validator import has_errors, validate_plan
from backend.workflow.models import NodeType

# evidence need → 需要 rag_retrieve
_RAG_EVIDENCE_NEEDS = frozenset({"historical_cases", "traffic_rules", "knowledge"})
# evidence need → 需要 memory_context
_MEMORY_EVIDENCE_NEEDS = frozenset({"memory", "historical_context", "prior_decisions"})


def _validate_snapshot_hash(proposal: PlanProposal, snapshot: PlannerCapabilitySnapshot) -> None:
    """proposal 的 capabilitySnapshotHash 必须与当前 snapshot 一致，否则 SNAPSHOT_MISMATCH。"""
    if proposal.capabilitySnapshotHash and proposal.capabilitySnapshotHash != snapshot.snapshotHash:
        raise PlannerFailure(
            PlannerFailureCode.SNAPSHOT_MISMATCH,
            f"proposal 基于 snapshot '{proposal.capabilitySnapshotHash}'，当前为 '{snapshot.snapshotHash}'",
            retryable=False,
        )


def _validate_dependencies(proposal: PlanProposal) -> None:
    """依赖存在性 + LINEAR-only 校验。"""
    ids = [s.proposalStepId for s in proposal.steps]
    id_set = set(ids)

    for i, step in enumerate(proposal.steps):
        deps = step.dependsOnProposalStepIds or []
        for dep in deps:
            if dep not in id_set:
                raise PlannerFailure(
                    PlannerFailureCode.COMPILE_ERROR,
                    f"步骤 '{step.proposalStepId}' 依赖不存在的 proposalStepId '{dep}'",
                )
        # LINEAR-only：每个步骤最多依赖前一个步骤
        allowed = [] if i == 0 else [ids[i - 1]]
        if deps and deps != allowed:
            raise PlannerFailure(
                PlannerFailureCode.UNSUPPORTED_PLAN_SHAPE,
                f"步骤 '{step.proposalStepId}' 依赖 {deps} 不是线性（仅允许依赖前一步骤 {allowed}）",
            )


def _collect_evidence_needs(proposal: PlanProposal) -> set:
    needs: set = set(proposal.evidenceNeeds or [])
    for s in proposal.steps:
        needs.update(s.evidenceNeeds or [])
    return needs


def _resolve_agent(step: PlanProposalStep, snapshot: PlannerCapabilitySnapshot) -> Optional[str]:
    """解析 proposal step 的 agent capability → execution agent type。

    requiredCapabilities 中命中 agent capability 的第一个。
    """
    for cap_id in step.requiredCapabilities:
        cap = snapshot.get_agent_capability(cap_id)
        if cap is not None and cap.plannerEligible:
            return cap.executionAgentType
    return None


def _resolve_action(step: PlanProposalStep, snapshot: PlannerCapabilitySnapshot) -> Optional[str]:
    """解析 action capability → execution action type。"""
    action_caps = [c for c in step.requiredCapabilities if snapshot.get_action_capability(c) is not None]
    if not action_caps:
        return None
    if len(action_caps) != 1:
        raise PlannerFailure(
            PlannerFailureCode.COMPILE_ERROR,
            f"action 步骤 '{step.proposalStepId}' 必须恰好声明 1 个 action capability，实际 {len(action_caps)}",
        )
    cap = snapshot.get_action_capability(action_caps[0])
    if cap is None or not cap.plannerEligible:
        raise PlannerFailure(
            PlannerFailureCode.UNSUPPORTED_CAPABILITY,
            f"action capability '{action_caps[0]}' 不是 planner-eligible（无端到端执行器）",
        )
    return cap.executionActionType


def _agent_slug(agent_type: str) -> str:
    slug = agent_type.lower()
    if slug.endswith("agent"):
        slug = slug[:-len("agent")]
    return slug


def _next_step_id(kind: str, slug: str, counters: Dict[str, int]) -> str:
    key = f"{kind}_{slug}"
    n = counters.get(key, 0) + 1
    counters[key] = n
    return f"{kind}_{slug}_{n:02d}"


def _action_meta(action_type: str):
    return get_tool_registry().get(action_type)


def compile_proposal(
    proposal: PlanProposal,
    snapshot: PlannerCapabilitySnapshot,
    ctx: PlanningContext,
) -> Plan:
    """确定性编译 proposal → canonical Plan。任何 unsupported → PlannerFailure。"""
    _validate_snapshot_hash(proposal, snapshot)
    _validate_dependencies(proposal)
    evidence_needs = _collect_evidence_needs(proposal)

    steps: List[PlanStep] = []
    counters: Dict[str, int] = {}
    registry = get_tool_registry()

    # ── 1. validate_event（ALWAYS）────────────────────────────────
    steps.append(PlanStep(
        stepId="validate_event",
        stepType=NodeType.VALIDATE_EVENT,
        objective="校验事件字段完整性并标准化事件类型",
    ))

    # ── 2. rule_router（ALWAYS）───────────────────────────────────
    steps.append(PlanStep(
        stepId="rule_router",
        stepType=NodeType.RULE_ROUTER,
        objective="根据事件类型与风险特征确定处置路线与审批需求",
    ))

    # ── 3. rag_retrieve（CONDITIONAL）─────────────────────────────
    if evidence_needs & _RAG_EVIDENCE_NEEDS:
        steps.append(PlanStep(
            stepId="rag_retrieve",
            stepType=NodeType.RAG_RETRIEVE,
            objective="检索相关预案、历史案例与处置经验",
            timeoutSeconds=15,
        ))

    # ── 4. memory_context（CONDITIONAL）───────────────────────────
    if evidence_needs & _MEMORY_EVIDENCE_NEEDS:
        steps.append(PlanStep(
            stepId="memory_context",
            stepType=NodeType.MEMORY_CONTEXT,
            objective="加载该路段历史决策与稳定事实",
            timeoutSeconds=10,
        ))

    # ── 5. agent_task（SEMANTIC，从 proposal）─────────────────────
    agent_count = 0
    for ps in proposal.steps:
        if ps.actionIntent:
            continue  # action 步骤稍后处理
        agent_type = _resolve_agent(ps, snapshot)
        if agent_type is None:
            if ps.evidenceNeeds:
                continue  # evidence-only 步骤不生成节点
            raise PlannerFailure(
                PlannerFailureCode.UNSUPPORTED_CAPABILITY,
                f"步骤 '{ps.proposalStepId}' 未声明可解析的 agent capability",
            )
        steps.append(PlanStep(
            stepId=_next_step_id("agent", _agent_slug(agent_type), counters),
            stepType=NodeType.AGENT_TASK,
            objective=ps.expectedOutcome or f"{agent_type} 分析研判",
            agentType=agent_type,
            timeoutSeconds=30,
            retryPolicy={"maxRetries": 1},
        ))
        agent_count += 1

    # ── 6. evidence_evaluate（CONDITIONAL）────────────────────────
    if agent_count > 0:
        steps.append(PlanStep(
            stepId="evidence_evaluate",
            stepType=NodeType.EVIDENCE_EVALUATE,
            objective="评估 Agent 输出与 RAG 证据质量",
        ))

    # ── 7. risk_gate（ALWAYS）─────────────────────────────────────
    steps.append(PlanStep(
        stepId="risk_gate",
        stepType=NodeType.RISK_GATE,
        objective="风险门控：高风险需人工审批",
        approvalRequired=ctx.requires_approval,
    ))

    # ── 8. action（SEMANTIC，从 proposal）+ Approval Identity V2 ──
    for ps in proposal.steps:
        if not ps.actionIntent:
            continue
        action_type = _resolve_action(ps, snapshot)
        if action_type is None:
            raise PlannerFailure(
                PlannerFailureCode.UNSUPPORTED_CAPABILITY,
                f"action 步骤 '{ps.proposalStepId}' 未声明可解析的 action capability",
            )
        meta = _action_meta(action_type)
        if meta is None:
            raise PlannerFailure(
                PlannerFailureCode.UNSUPPORTED_CAPABILITY,
                f"action '{action_type}' 未注册",
            )

        # parameterHints 归一化（required 缺失 → compile error）
        params = normalize_parameter_hints(action_type, ps.parameterHints or {})
        if params is None:
            raise PlannerFailure(
                PlannerFailureCode.INVALID_PARAMETER_HINTS,
                f"action '{action_type}' 的 parameterHints 缺少 required 字段",
            )

        # canonical stepId + Approval Identity V2
        action_step_id = _next_step_id("action", action_type, counters)

        if meta.approvalRequired:
            # 独立 human_approval gate，绑定 target actionStepId
            approval_step_id = _next_step_id("approval", action_type, counters)
            steps.append(PlanStep(
                stepId=approval_step_id,
                stepType=NodeType.HUMAN_APPROVAL,
                objective=f"人工审批 {action_type}",
                actionType=action_type,
                riskLevel=meta.riskLevel.value,
                approvalRequired=True,
                expectedOutcome="批准后方可执行对应 action",
                metadata={
                    "approvalIdentityVersion": 2,
                    "targetActionStepId": action_step_id,
                },
            ))

        steps.append(PlanStep(
            stepId=action_step_id,
            stepType=NodeType.ACTION,
            objective=ps.expectedOutcome or f"执行动作 {action_type}",
            toolName=action_type,
            actionType=action_type,
            riskLevel=meta.riskLevel.value,
            approvalRequired=meta.approvalRequired,
            retryPolicy=dict(meta.retryPolicy),
            timeoutSeconds=int(meta.timeoutSeconds),
            metadata={
                "approvalIdentityVersion": 2,
                "paramsTemplate": params,
            },
        ))

    # ── 9. save_result（ALWAYS，闭环持久化）──────────────────────
    save_meta = registry.get("save_result")
    steps.append(PlanStep(
        stepId=_next_step_id("action", "save_result", counters),
        stepType=NodeType.ACTION,
        objective="执行动作 save_result",
        toolName="save_result",
        actionType="save_result",
        riskLevel=save_meta.riskLevel.value if save_meta else "write",
        approvalRequired=save_meta.approvalRequired if save_meta else False,
        retryPolicy=dict(save_meta.retryPolicy) if save_meta else {},
        timeoutSeconds=int(save_meta.timeoutSeconds) if save_meta else 30,
        metadata={"approvalIdentityVersion": 2},
    ))

    # ── 10. close（ALWAYS）───────────────────────────────────────
    steps.append(PlanStep(
        stepId="close",
        stepType=NodeType.CLOSE,
        objective="汇总结果并闭环归档",
    ))

    # ── 线性 wiring：每步 dependsOn 前一步 ────────────────────────
    for i in range(1, len(steps)):
        steps[i].dependsOn = [steps[i - 1].stepId]

    assumptions = list(proposal.assumptions or [])
    if evidence_needs & {"current_traffic_state", "simulation_context"}:
        assumptions.append("runtime_evidence: current_traffic_state/simulation_context 由运行时注入")

    plan = Plan(
        planId=generate_plan_id(),
        planFingerprint=compute_fingerprint(steps),
        goal=proposal.goal or ctx.user_goal or "交通事件研判处置",
        goalType=ctx.goal_type,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=1,
        steps=steps,
        planningMode=PlanningMode.LLM_ASSISTED,
        createdBy="planner:llm_v1",
        eventId=ctx.normalized_event.get("eventId") or ctx.normalized_event.get("event_id"),
        confidence=proposal.confidence,
        assumptions=assumptions,
        constraints=dict(ctx.constraints),
        evidenceRefs=[],
        memoryRefs=[],
        approvalIdentityVersion=2,
    )

    # ── 复用现有 validate_plan() fail-closed ──────────────────────
    issues = validate_plan(plan)
    if has_errors(issues):
        raise PlannerFailure(
            PlannerFailureCode.COMPILE_ERROR,
            "compiled plan 校验失败: " + "; ".join(f"{i.code}" for i in issues),
        )

    return plan
