"""
Trajectory Metrics — Phase17 Round3 P1

属 execution lineage（rootRunId scoped）。允许传入任意 lineage runId，backend resolve root。
所有 metrics 实时聚合现有 durable 数据，无新表。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.planning.budget import get_lineage
from backend.planning.rejection import intent_family, ActionIntentFamily
from backend.planning.loop_guard import canonicalize_params
from backend.workflow.models import NodeType

# 结构节点不计 trajectoryLength
_STRUCTURAL_NODE_TYPES = frozenset({
    "trigger", "close", "human_approval", "wait", "parallel", "join", "monitor",
})


def resolve_root_run_id(repo, run_id: str) -> str:
    """向上走到 root（无 replannedFromRunId 的 run）。"""
    seen = set()
    cur = run_id
    while cur and cur not in seen:
        seen.add(cur)
        run = repo.get_run(cur)
        if run is None:
            break
        state = run.state if isinstance(run.state, dict) else {}
        from_run = state.get("replannedFromRunId")
        if not from_run:
            return cur
        cur = from_run
    return run_id


def build_lineage_runs(repo, root_run_id: str) -> List[Any]:
    """从 root 沿 replannedToRunId 向下走，得到有序 lineage runs。"""
    runs = []
    seen = set()
    cur = root_run_id
    while cur and cur not in seen:
        seen.add(cur)
        run = repo.get_run(cur)
        if run is None:
            break
        runs.append(run)
        state = run.state if isinstance(run.state, dict) else {}
        cur = state.get("replannedToRunId") or None
    return runs


def _collect_observations(repo, run_ids: List[str]) -> List[Dict[str, Any]]:
    obs = []
    for rid in run_ids:
        for e in repo.list_observations(rid):
            payload = e.payload if isinstance(e.payload, dict) else {}
            payload = dict(payload)
            payload.setdefault("_runId", rid)
            obs.append(payload)
    return obs


def _collect_recoveries(repo, run_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """收集 recovery_started/completed，按 recoveryAttemptId 配对。"""
    attempts: Dict[str, Dict[str, Any]] = {}
    for rid in run_ids:
        for e in repo.list_events(rid):
            if e.event_type not in ("recovery_started", "recovery_completed"):
                continue
            payload = e.payload if isinstance(e.payload, dict) else {}
            aid = payload.get("recoveryAttemptId", "")
            if not aid:
                continue
            a = attempts.setdefault(aid, {"attemptId": aid, "startedAt": None, "completedAt": None, "outcome": None})
            if e.event_type == "recovery_started":
                a["startedAt"] = payload.get("startedAt")
            else:
                a["completedAt"] = payload.get("completedAt")
                a["outcome"] = payload.get("outcome")
    return attempts


def compute_trajectory(repo, run_id: str) -> Dict[str, Any]:
    """计算 rootRunId lineage 的 trajectory。"""
    root_run_id = resolve_root_run_id(repo, run_id)
    runs = build_lineage_runs(repo, root_run_id)
    run_ids = [r.run_id for r in runs]

    root = runs[0] if runs else None
    plan_id = root.definition_id if root else ""

    # lineage 结构（parent/child 指针）
    lineage_info = []
    for r in runs:
        state = r.state if isinstance(r.state, dict) else {}
        lineage_info.append({
            "runId": r.run_id,
            "version": r.version,
            "status": r.status.value,
            "parentRunId": state.get("replannedFromRunId"),
            "childRunId": state.get("replannedToRunId"),
            "terminationReason": state.get("terminationReason"),
            "startedAt": r.started_at or None,
            "completedAt": r.completed_at or None,
        })

    # finalOutcome = canonical leaf（最后一个无 child 的 run）
    leaf = runs[-1] if runs else None

    # metrics
    revision_count = len({r.version for r in runs})
    replan_count = sum(1 for r in runs if (r.state or {}).get("replannedFromRunId") if isinstance(r.state, dict))

    observations = _collect_observations(repo, run_ids)
    recoveries = _collect_recoveries(repo, run_ids)

    recovery_attempts = len(recoveries)
    recovery_success = sum(1 for a in recoveries.values() if a["outcome"] == "completed")

    def _iso_to_sec(iso):
        if not iso:
            return None
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None

    paired_success_times = []
    for a in recoveries.values():
        if a["outcome"] == "completed" and a["startedAt"] and a["completedAt"]:
            s = _iso_to_sec(a["startedAt"])
            c = _iso_to_sec(a["completedAt"])
            if s is not None and c is not None and c >= s:
                paired_success_times.append(c - s)
    avg_recovery_sec = round(sum(paired_success_times) / len(paired_success_times), 3) if paired_success_times else None

    budget_exhaustions = sum(1 for o in observations if o.get("type") == "budget_exhausted")
    loop_stops = sum(1 for o in observations if o.get("type") == "loop_detected")
    tool_denials = sum(1 for o in observations if o.get("type") == "tool_denied")

    # humanInterventions
    human_interventions = 0
    for rid in run_ids:
        for a in repo.list_approvals(rid):
            if a.decision.value != "pending":
                human_interventions += 1

    # carriedForwardCount（lineage 使用的 revisions 中 carried steps）
    carried_forward_count = 0
    seen_versions = set()
    for r in runs:
        if r.version in seen_versions:
            continue
        seen_versions.add(r.version)
        definition = repo.get_definition(r.definition_id)
        if definition is None:
            continue
        plan_raw = (definition.metadata or {}).get("plan")
        if not plan_raw:
            continue
        if isinstance(plan_raw, str):
            import json as _j
            try:
                plan_raw = _j.loads(plan_raw)
            except Exception:
                continue
        for s in plan_raw.get("steps", []):
            meta = s.get("metadata") or {}
            if meta.get("carriedForward"):
                carried_forward_count += 1

    # duplicateSideEffectCount（HIGH_RISK_NON_IDEMPOTENT，同 semantic signature SUCCEEDED >1）
    duplicate_side_effect = _compute_duplicate_side_effect(repo, run_ids)

    # trajectoryLength（semantic node_runs，排除结构节点）
    trajectory_length = 0
    for rid in run_ids:
        for nr in repo.get_node_runs(rid):
            if nr.node_type.value not in _STRUCTURAL_NODE_TYPES:
                trajectory_length += 1

    return {
        "canonicalRootRunId": root_run_id,
        "planId": plan_id,
        "finalOutcome": leaf.status.value if leaf else None,
        "lineage": lineage_info,
        "metrics": {
            "revisionCount": revision_count,
            "replanCount": replan_count,
            "recoveryAttempts": recovery_attempts,
            "recoverySuccess": recovery_success,
            "recoveryRate": (recovery_success / recovery_attempts) if recovery_attempts else None,
            "averageTimeToRecoverySeconds": avg_recovery_sec,
            "budgetExhaustions": budget_exhaustions,
            "loopStops": loop_stops,
            "toolDenials": tool_denials,
            "humanInterventions": human_interventions,
            "carriedForwardCount": carried_forward_count,
            "duplicateSideEffectCount": duplicate_side_effect,
            "trajectoryLength": trajectory_length,
        },
        "observationSummary": {
            "total": len(observations),
            "byType": _count_by(observations, "type"),
        },
    }


def _count_by(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        k = it.get(key, "unknown")
        out[k] = out.get(k, 0) + 1
    return out


def _compute_duplicate_side_effect(repo, run_ids: List[str]) -> int:
    """HIGH_RISK_NON_IDEMPOTENT 同 semantic signature SUCCEEDED >1 → sum(max(count-1,0))。"""
    from backend.workflow.models import ActionStatus
    from backend.workflow.recovery import RecoverySafetyClass, RecoverySafetyClassifier

    classifier = RecoverySafetyClassifier()
    sig_count: Dict[str, int] = {}
    for rid in run_ids:
        for rec in repo.list_action_records(rid):
            if rec.status != ActionStatus.SUCCEEDED:
                continue
            cls = classifier.classify_node("action", rec.action_type)
            if cls != RecoverySafetyClass.HIGH_RISK_NON_IDEMPOTENT:
                continue
            # canonical semantic signature：actionType + canonical params（排除瞬态）
            params = rec.params if isinstance(rec.params, dict) else {}
            sig = rec.action_type + ":" + _canonical_params_str(canonicalize_params(params))
            sig_count[sig] = sig_count.get(sig, 0) + 1
    return sum(max(c - 1, 0) for c in sig_count.values())


def _canonical_params_str(params: Dict[str, Any]) -> str:
    import json
    return json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
