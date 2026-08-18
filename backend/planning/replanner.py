"""
Deterministic Replanner — Phase 17 Round 2

只支持 LINEAR：completed prefix + unresolved suffix。
completed prefix immutable（carried-forward）；只 replan unresolved suffix。
只 PROPOSE 新 Plan revision，不 execute node/tool/approval。
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.planning.models import (
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    compute_fingerprint,
)


def _carried_step(step: PlanStep, from_version: int, from_run_id: str, result_ref: str) -> PlanStep:
    """将 step 标记为 carried-forward（不进入 child executable graph）。"""
    return PlanStep(
        stepId=step.stepId,
        stepType=step.stepType,
        objective=step.objective,
        dependsOn=list(step.dependsOn),
        agentType=step.agentType,
        toolName=step.toolName,
        actionType=step.actionType,
        preconditions=list(step.preconditions),
        expectedOutcome=step.expectedOutcome,
        riskLevel=step.riskLevel,
        approvalRequired=step.approvalRequired,
        evidenceRefs=list(step.evidenceRefs),
        retryPolicy=dict(step.retryPolicy),
        timeoutSeconds=step.timeoutSeconds,
        resultRef=result_ref,
        metadata={
            "carriedForward": True,
            "carriedForwardFromVersion": from_version,
            "carriedForwardFromRunId": from_run_id,
        },
    )


def build_revision(
    plan: Plan,
    completed_result_refs: Dict[str, str],
    from_run_id: str,
    constraints: Dict[str, Any] = None,
) -> Plan:
    """构建新 revision。

    Args:
        plan: 当前（父）Plan。
        completed_result_refs: {stepId: resultRef}，已完成步骤（含 external side effect）。
        from_run_id: 父 run id（carriedForwardFromRunId）。
        constraints: 继承的约束（写入 Plan.constraints，供 validator/replanner 把关）。

    Returns:
        新 Plan：same planId，version+1，新 fingerprint，completed prefix carried。
    """
    carried_ids = set(completed_result_refs.keys())
    new_steps: List[PlanStep] = []
    for s in plan.steps:
        if s.stepId in carried_ids:
            new_steps.append(_carried_step(s, plan.version, from_run_id, completed_result_refs[s.stepId]))
        else:
            new_steps.append(s)  # unresolved suffix（re-attempt）

    merged_constraints = dict(plan.constraints)
    if constraints:
        merged_constraints.update(constraints)

    return Plan(
        planId=plan.planId,
        planFingerprint=compute_fingerprint(new_steps),
        goal=plan.goal,
        goalType=plan.goalType,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=plan.version + 1,
        steps=new_steps,
        planningMode=plan.planningMode,
        createdBy=plan.createdBy,
        createdAt=plan.createdAt,
        updatedAt="",
        eventId=plan.eventId,
        confidence=plan.confidence,
        assumptions=list(plan.assumptions),
        constraints=merged_constraints,
        evidenceRefs=list(plan.evidenceRefs),
        memoryRefs=list(plan.memoryRefs),
        metadata=dict(plan.metadata),
    )


def is_carried(step: PlanStep) -> bool:
    return bool(step.metadata.get("carriedForward"))
