"""
Deterministic Planner — Phase 17 Round 1

build_plan(ctx) -> Plan

纯函数 / 确定性：
  - 无 LLM、无工具调用、无 DB 写、无网络副作用
  - Agent selection 只使用 Router candidates
  - Action selection 只使用 ActionCandidateResolver

典型逻辑（线性计划）：
  validate_event → rule_router → rag_retrieve → memory_context
  → agent_task* → evidence_evaluate → risk_gate
  → [human_approval → action]*（high-risk 独立门禁）→ action(save_result) → close
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.planning.action_resolver import ActionCandidateResolver, ActionResolution
from backend.planning.context import PlanningContext
from backend.planning.models import (
    EXECUTABLE_AGENT_TYPES,
    STRUCTURAL_AGENT_TYPES,
    UNSUPPORTED_AGENT_TYPES,
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    compute_fingerprint,
    generate_plan_id,
)
from backend.workflow.models import NodeType


def _map_agents(selected_agents) -> tuple:
    """将 router 选中的 Agent 显式映射为（可执行 agent，说明）。

    不进行静默语义替换：
      - FusionAgent/ReportAgent 是结构性 fusion/report 角色 → 不生成 agent_task，
        由 evidence_evaluate + close 承载（记录说明）。
      - PublicSafetyAgent 无运行时实现 → 不伪造，记录 unsupported 说明。
    """
    executable: List[str] = []
    notes: List[str] = []
    for a in selected_agents:
        if a in EXECUTABLE_AGENT_TYPES:
            executable.append(a)
        elif a in STRUCTURAL_AGENT_TYPES:
            notes.append(f"{a}:structural_fusion_role")
        elif a in UNSUPPORTED_AGENT_TYPES:
            notes.append(f"{a}:unsupported_no_implementation")
        else:
            notes.append(f"{a}:unknown_mapping")
    return executable, notes


def _agent_step_id(agent_type: str) -> str:
    """agentType → 确定性 stepId（如 CongestionAgent → agent_congestion）。"""
    slug = agent_type.lower()
    if slug.endswith("agent"):
        slug = slug[:-len("agent")]
    return f"agent_{slug}"


def _action_step_id(action_type: str) -> str:
    return f"action_{action_type}"


def _approval_step_id(action_type: str) -> str:
    return f"human_approval_{action_type}"


def _extract_evidence_refs(rag_evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 RAG 证据提取引用。缺失 id 的条目跳过（不伪造 citation）。"""
    refs: List[Dict[str, Any]] = []
    for r in rag_evidence.get("results", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("evidenceId") or r.get("docId")
        if rid:
            refs.append({
                "id": rid,
                "source": r.get("source", "rag"),
                "score": r.get("score", r.get("similarity", r.get("rerank_score"))),
            })
    return refs


def _extract_memory_refs(memory_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 Memory 上下文提取稳定事实引用（键值）。"""
    refs: List[Dict[str, Any]] = []
    for fact in memory_context.get("stableFacts", []):
        if isinstance(fact, dict):
            key = fact.get("memoryKey") or fact.get("key")
            if key:
                refs.append({"key": key, "value": fact.get("value", fact.get("val", ""))})
    return refs


def _derive_assumptions(ctx: PlanningContext) -> List[str]:
    """确定性记录计划假设（unknown / 缺失证据）。"""
    assumptions: List[str] = []
    unknown_fields = ctx.normalized_event.get("unknownFields", [])
    if unknown_fields:
        assumptions.append(f"unknown_fields: {', '.join(sorted(unknown_fields))}")
    if not ctx.rag_evidence.get("results"):
        assumptions.append("no_rag_evidence_available")
    if ctx.has_simulation_context():
        assumptions.append("simulation_context_present")
    return assumptions


def build_plan(ctx: PlanningContext) -> Plan:
    """确定性构建计划。

    Args:
        ctx: 计划上下文。

    Returns:
        Plan（定义态 DRAFT；planId 由 generate_plan_id 生成，preview 时被丢弃）。
    """
    steps: List[PlanStep] = []

    # ── 1. validate_event ──────────────────────────────────────
    steps.append(PlanStep(
        stepId="validate_event",
        stepType=NodeType.VALIDATE_EVENT,
        objective="校验事件字段完整性并标准化事件类型",
    ))

    # ── 2. rule_router ─────────────────────────────────────────
    steps.append(PlanStep(
        stepId="rule_router",
        stepType=NodeType.RULE_ROUTER,
        objective="根据事件类型与风险特征确定处置路线与审批需求",
    ))

    # ── 3. rag_retrieve ────────────────────────────────────────
    steps.append(PlanStep(
        stepId="rag_retrieve",
        stepType=NodeType.RAG_RETRIEVE,
        objective="检索相关预案、历史案例与处置经验",
        timeoutSeconds=15,
    ))

    # ── 4. memory_context ──────────────────────────────────────
    steps.append(PlanStep(
        stepId="memory_context",
        stepType=NodeType.MEMORY_CONTEXT,
        objective="加载该路段历史决策与稳定事实",
        timeoutSeconds=10,
    ))

    # ── 5. agent_task*（只使用 Router candidates，显式映射）─────
    executable_agents, agent_notes = _map_agents(ctx.selected_agents)
    for agent in executable_agents:
        steps.append(PlanStep(
            stepId=_agent_step_id(agent),
            stepType=NodeType.AGENT_TASK,
            objective=f"{agent} 分析研判",
            agentType=agent,
            timeoutSeconds=30,
            retryPolicy={"maxRetries": 1},
        ))

    # ── 6. evidence_evaluate ───────────────────────────────────
    steps.append(PlanStep(
        stepId="evidence_evaluate",
        stepType=NodeType.EVIDENCE_EVALUATE,
        objective="评估 Agent 输出与 RAG 证据质量",
    ))

    # ── 7. risk_gate ───────────────────────────────────────────
    steps.append(PlanStep(
        stepId="risk_gate",
        stepType=NodeType.RISK_GATE,
        objective="风险门控：高风险需人工审批",
        approvalRequired=ctx.requires_approval,
    ))

    # ── 8. 动作候选（只使用 ActionCandidateResolver）───────────
    resolution: ActionResolution = ActionCandidateResolver().resolve(ctx)
    for cand in resolution.candidates:
        if cand.approvalRequired:
            # 每个 high-risk action 有独立 approval gate
            steps.append(PlanStep(
                stepId=_approval_step_id(cand.actionType),
                stepType=NodeType.HUMAN_APPROVAL,
                objective=f"人工审批 {cand.actionType}",
                actionType=cand.actionType,
                riskLevel=cand.riskLevel,
                approvalRequired=True,
                expectedOutcome="批准后方可执行对应 action",
            ))
        steps.append(PlanStep(
            stepId=_action_step_id(cand.actionType),
            stepType=NodeType.ACTION,
            objective=f"执行动作 {cand.actionType}",
            toolName=cand.toolName,
            actionType=cand.actionType,
            riskLevel=cand.riskLevel,
            approvalRequired=cand.approvalRequired,
            retryPolicy=_retry_policy_for(ctx, cand.actionType),
            timeoutSeconds=_timeout_for(ctx, cand.actionType),
        ))

    # ── 9. close ───────────────────────────────────────────────
    steps.append(PlanStep(
        stepId="close",
        stepType=NodeType.CLOSE,
        objective="汇总结果并闭环归档",
    ))

    # ── 线性 wiring：每步 dependsOn 前一步 ─────────────────────
    for i in range(1, len(steps)):
        steps[i].dependsOn = [steps[i - 1].stepId]

    # ── 证据 / 假设 ────────────────────────────────────────────
    evidence_refs = _extract_evidence_refs(ctx.rag_evidence)
    memory_refs = _extract_memory_refs(ctx.memory_context)
    assumptions = _derive_assumptions(ctx)
    assumptions.extend(agent_notes)

    return Plan(
        planId=generate_plan_id(),
        planFingerprint=compute_fingerprint(steps),
        goal=ctx.user_goal or _default_goal(ctx),
        goalType=ctx.goal_type,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=1,
        steps=steps,
        eventId=ctx.normalized_event.get("eventId") or ctx.normalized_event.get("event_id"),
        assumptions=assumptions,
        constraints=dict(ctx.constraints),
        evidenceRefs=evidence_refs,
        memoryRefs=memory_refs,
    )


def _default_goal(ctx: PlanningContext) -> str:
    """无显式目标时，按事件类型/路段生成确定性目标文本。"""
    ev = ctx.normalized_event
    event_cn = ev.get("eventTypeCn", ev.get("eventType", ""))
    road = ev.get("roadName", "")
    if event_cn and road:
        return f"{road} {event_cn}处置"
    if event_cn:
        return f"{event_cn}处置"
    return "交通事件研判处置"


def _timeout_for(ctx: PlanningContext, action_type: str) -> int:
    meta = ctx.tool_registry.get(action_type)
    if meta is not None:
        return int(meta.timeoutSeconds)
    return 30


def _retry_policy_for(ctx: PlanningContext, action_type: str) -> Dict[str, Any]:
    meta = ctx.tool_registry.get(action_type)
    if meta is not None:
        return dict(meta.retryPolicy)
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 18 Round 1 — Planner Mode Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlanBuildResult:
    """plan + sanitized planner audit（LLM 模式含 proposal，失败含 failure）。"""
    plan: Plan
    planner_audit: Any  # PlannerAudit
    proposal: Any = None  # PlanProposal
    failure: Any = None   # PlannerFailure


def _deterministic_goal_coverage(ctx: PlanningContext) -> str:
    """deterministic capability checker：识别事件类型则 FULL，否则 UNKNOWN。

    不引入 LLM judge；宁可 UNKNOWN，不虚报 FULL。
    """
    if ctx.goal_type != GoalType.GENERIC:
        return "FULL"
    return "UNKNOWN"


async def build_plan_with_mode(
    ctx: PlanningContext,
    planner_mode: str = "deterministic",
    llm_client: Any = None,
) -> PlanBuildResult:
    """plannerMode 编排（async）。

    - deterministic：现有 build_plan()，零 LLM。
    - llm：LLM proposal → compile；失败 raise PlannerFailure（不 fallback）。
    - auto：LLM proposal → compile；失败 deterministic fallback（记录 fallbackReason）。

    Args:
        ctx: 计划上下文。
        planner_mode: "deterministic" | "llm" | "auto"。
        llm_client: 注入 LLM client（测试用）；None 则用默认 PlannerLLMClient。

    Returns:
        PlanBuildResult。

    Raises:
        PlannerFailure（仅 llm 模式失败时）。
    """
    import time

    from backend.planning.capability_snapshot import build_planner_capability_snapshot
    from backend.planning.llm_client import PlannerLLMClient
    from backend.planning.proposal import PlannerAudit, PlannerFailure
    from backend.planning.proposal_compiler import compile_proposal

    planner_mode = planner_mode or "deterministic"

    # ── deterministic：零 LLM ─────────────────────────────────────
    if planner_mode == "deterministic":
        plan = build_plan(ctx)
        audit = PlannerAudit(
            planningModeRequested="deterministic",
            planningModeUsed="deterministic",
            assumptions=list(plan.assumptions),
            goalCoverage=_deterministic_goal_coverage(ctx),
        )
        return PlanBuildResult(plan=plan, planner_audit=audit)

    snapshot = build_planner_capability_snapshot()
    client = llm_client or PlannerLLMClient()

    def _fallback(failure: PlannerFailure, latency_ms: float) -> PlanBuildResult:
        """auto fallback：复用 deterministic build_plan()，不伪装 LLM 成功。"""
        plan = build_plan(ctx)
        audit = PlannerAudit(
            planningModeRequested="auto",
            planningModeUsed="deterministic",
            assumptions=list(plan.assumptions),
            capabilitySnapshotVersion=snapshot.snapshotVersion,
            capabilitySnapshotHash=snapshot.snapshotHash,
            latencyMs=latency_ms,
            fallbackReason=failure.code,
            goalCoverage="UNKNOWN",
        )
        return PlanBuildResult(plan=plan, planner_audit=audit, failure=failure)

    t0 = time.time()
    try:
        proposal = await client.generate_proposal(ctx, snapshot, ctx.user_goal)
    except PlannerFailure as f:
        latency_ms = (time.time() - t0) * 1000.0
        if planner_mode == "auto":
            return _fallback(f, latency_ms)
        raise

    latency_ms = (time.time() - t0) * 1000.0
    try:
        plan = compile_proposal(proposal, snapshot, ctx)
    except PlannerFailure as f:
        if planner_mode == "auto":
            return _fallback(f, latency_ms)
        raise

    audit = PlannerAudit(
        planningModeRequested=planner_mode,
        planningModeUsed="llm",
        plannerModel=proposal.plannerModel or None,
        proposalId=proposal.proposalId,
        confidence=proposal.confidence,
        assumptions=list(plan.assumptions),
        plannerReasonSummary=proposal.plannerReasonSummary,
        capabilitySnapshotVersion=snapshot.snapshotVersion,
        capabilitySnapshotHash=snapshot.snapshotHash,
        attemptCount=getattr(client, "last_attempt_count", 1),
        latencyMs=latency_ms,
        usageSummary=dict(getattr(client, "last_usage", {})),
        goalCoverage="FULL",
    )
    return PlanBuildResult(plan=plan, planner_audit=audit, proposal=proposal)
