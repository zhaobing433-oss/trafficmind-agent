"""
Deterministic Version Diff — Phase17 Round3 P1

按 stepId 比较两个 frozen Plan 版本：added/removed/changed/carriedForward。
changed 只比较 fingerprint-relevant 结构字段（与 compute_fingerprint 语义一致）。
排除 runtime status / resultRef / timestamps / transient IDs / carried runtime projection。
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.planning.models import Plan, PlanStep


def step_structure(step: PlanStep) -> Dict[str, Any]:
    """指纹相关结构字段（与 compute_fingerprint 对齐，排除 runtime projection）。"""
    return {
        "stepType": step.stepType.value,
        "objective": step.objective,
        "dependsOn": list(step.dependsOn),
        "agentType": step.agentType,
        "toolName": step.toolName,
        "actionType": step.actionType,
        "riskLevel": step.riskLevel,
        "approvalRequired": step.approvalRequired,
        "timeoutSeconds": step.timeoutSeconds,
        "retryPolicy": step.retryPolicy,
    }


def compute_diff(plan_from: Plan, plan_to: Plan) -> Dict[str, List[str]]:
    """比较 from → to，返回 added/removed/changed/carriedForward 的 stepId 列表。"""
    steps_from = {s.stepId: s for s in plan_from.steps}
    steps_to = {s.stepId: s for s in plan_to.steps}

    added = [sid for sid in steps_to if sid not in steps_from]
    removed = [sid for sid in steps_from if sid not in steps_to]
    changed = [
        sid for sid in steps_from
        if sid in steps_to and step_structure(steps_from[sid]) != step_structure(steps_to[sid])
    ]
    carried = [s.stepId for s in plan_to.steps if s.metadata.get("carriedForward")]

    return {
        "addedSteps": added,
        "removedSteps": removed,
        "changedSteps": changed,
        "carriedForwardSteps": carried,
    }
