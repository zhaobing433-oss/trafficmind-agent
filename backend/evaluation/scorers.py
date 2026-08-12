"""Deterministic scorers — no LLM dependency."""

from typing import Any, Dict, List, Optional, Tuple
from backend.evaluation.models import (
    EvaluationCase, ExpectedEvent, ExpectedRouting, ExpectedConflict,
    ExpectedPolicy, ExpectedWorkflow, ExpectedOutput, CaseScore,
)

# Canonical event type normalization
EVENT_TYPE_CANONICAL = {
    "拥堵": "congestion", "交通拥堵": "congestion", "congestion": "congestion",
    "事故": "accident", "交通事故": "accident", "accident": "accident",
    "signal_fault": "signal_fault", "信号异常": "signal_fault", "信号灯异常": "signal_fault", "信号灯故障": "signal_fault",
    "illegal_parking": "illegal_parking", "违停": "illegal_parking",
    "wrong_way": "wrong_way", "逆行": "wrong_way",
    "pedestrian_intrusion": "pedestrian_intrusion", "行人闯入": "pedestrian_intrusion",
    "vehicle_stopped": "vehicle_stopped", "车辆滞留": "vehicle_stopped",
    "construction_block": "construction_block", "施工占道": "construction_block", "施工": "construction_block",
}

def _canonical_event_type(val: Any) -> str:
    return EVENT_TYPE_CANONICAL.get(str(val or "").strip(), str(val or "").strip())


def score_event_parsing(expected: ExpectedEvent, actual_event: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score event field accuracy with boolean match and numeric tolerance."""
    assertions: List[str] = []
    total_checks = 0; passed = 0
    for field, exp_val in expected.expectedFields.items():
        total_checks += 1
        actual = actual_event.get(field)
        if field in expected.numericTolerance:
            tol = expected.numericTolerance[field]
            try:
                if abs(float(actual or 0) - float(exp_val)) <= tol:
                    passed += 1
                else:
                    assertions.append(f"EVENT:{field}: expected ~{exp_val}, got {actual} (tolerance={tol})")
            except (ValueError, TypeError):
                assertions.append(f"EVENT:{field}: numeric comparison failed")
        elif field in expected.booleanFields:
            if bool(actual) == bool(exp_val):
                passed += 1
            else:
                assertions.append(f"EVENT:{field}: expected {exp_val}, got {actual}")
        elif field in ("eventType", "eventTypeCn"):
            if _canonical_event_type(actual) == _canonical_event_type(exp_val):
                passed += 1
            else:
                assertions.append(f"EVENT:{field}: expected '{_canonical_event_type(exp_val)}', got '{_canonical_event_type(actual)}'")
        else:
            if str(actual or "") == str(exp_val or ""):
                passed += 1
            else:
                assertions.append(f"EVENT:{field}: expected '{exp_val}', got '{actual}'")
    for field, exp_bool in expected.booleanFields.items():
        if field not in expected.expectedFields:
            total_checks += 1
            if bool(actual_event.get(field)) == bool(exp_bool):
                passed += 1
            else:
                assertions.append(f"EVENT:{field}: expected {exp_bool}, got {actual_event.get(field)}")
    if total_checks == 0:
        return 1.0, []  # no fields to check = full pass
    score = passed / total_checks
    return round(score, 4), assertions


def score_routing(expected: ExpectedRouting, selected: List[str]) -> Dict[str, Any]:
    required = set(expected.requiredAgents)
    forbidden = set(expected.forbiddenAgents)
    selected_set = set(selected)
    recall = 1.0 if len(required) == 0 else len(required & selected_set) / len(required)
    forbidden_hit = len(forbidden & selected_set) if forbidden else 0
    # forbiddenAgentRate score: 1.0 = no forbidden agents selected (perfect)
    forbidden_score = 1.0 - (forbidden_hit / max(len(selected_set), 1))
    # Exact match: all required present AND no forbidden present
    exact = 1.0 if (required.issubset(selected_set) and forbidden_hit == 0) else 0.0
    return {"requiredAgentRecall": round(recall, 4), "agentExactMatch": exact, "forbiddenAgentRate": round(forbidden_score, 4)}


def score_conflict(expected: ExpectedConflict, conflicts: List[Dict]) -> Dict[str, float]:
    has_conflict = len(conflicts) > 0
    conflict_ok = has_conflict == expected.required if expected.required else True
    if expected.allowedTypes and conflicts:
        actual_types = {c.get("type", "") for c in conflicts if isinstance(c, dict)}
        type_ok = all(t in expected.allowedTypes for t in actual_types)
    else:
        type_ok = True
    return {"conflictRequiredMatch": 1.0 if conflict_ok else 0.0, "conflictTypeMatch": 1.0 if type_ok else 0.0}


def score_safety_policy(expected: ExpectedPolicy, result: Dict[str, Any]) -> float:
    if expected.requiresHumanReview is not None:
        actual = result.get("requiresHumanReview", result.get("requires_human_review"))
        return 1.0 if bool(actual) == expected.requiresHumanReview else 0.0
    return 1.0


def score_workflow_invariants(expected: ExpectedWorkflow, state: Dict[str, Any]) -> float:
    inv_checks = 1; ok = 0
    if expected.requiredNodes:
        inv_checks = len(expected.requiredNodes)
        ok = sum(1 for n in expected.requiredNodes if n in str(state))
    if expected.forbiddenTransitions:
        inv_checks += len(expected.forbiddenTransitions)
        for t in expected.forbiddenTransitions:
            if t not in str(state): ok += 1
    return round(ok / max(inv_checks, 1), 4)


def score_output_structure(expected: ExpectedOutput, output: Dict[str, Any]) -> float:
    if not expected.requiredFields: return 1.0
    present = sum(1 for f in expected.requiredFields if f in output)
    return round(present / len(expected.requiredFields), 4)


def score_case(case: EvaluationCase, actual: Dict[str, Any]) -> CaseScore:
    # Extract simplified event from current_event (strip metadata keys)
    event_data = actual.get("event", {})
    simple_event = {k: v for k, v in event_data.items() if k not in ("fieldSources", "contextPolicy", "originalInput")}

    event_score, event_assertions = score_event_parsing(case.expected.event, simple_event)
    routing_scores = score_routing(case.expected.routing, actual.get("selectedAgents", []))
    conflict_scores = score_conflict(case.expected.conflict, actual.get("conflicts", []))
    safety = score_safety_policy(case.expected.policy, actual.get("policy", actual))
    # Workflow: only score if workflow fields are expected, else skip (1.0)
    if case.expected.workflow.requiredNodes or case.expected.workflow.forbiddenTransitions:
        workflow = score_workflow_invariants(case.expected.workflow, actual.get("state", actual))
    else:
        workflow = 1.0
    output_struct = score_output_structure(case.expected.output, actual.get("output", actual))

    all_scores = {
        "eventFieldAccuracy": event_score,
        **routing_scores,
        **conflict_scores,
        "conflictF1": (2 * conflict_scores.get("conflictRequiredMatch", 1.0) * conflict_scores.get("conflictTypeMatch", 1.0)
                       / max(conflict_scores.get("conflictRequiredMatch", 0) + conflict_scores.get("conflictTypeMatch", 0), 0.001)),
        "safetyPolicyPassRate": safety,
        "workflowInvariantPassRate": workflow,
        "outputStructurePassRate": output_struct,
    }
    # Core overall: 7 equal-weight metrics (excludes agentExactMatch — diagnostic only)
    core_keys = ["eventFieldAccuracy", "requiredAgentRecall", "forbiddenAgentRate",
                 "conflictF1", "safetyPolicyPassRate", "workflowInvariantPassRate", "outputStructurePassRate"]
    overall = round(sum(all_scores.get(k, 0.0) for k in core_keys) / len(core_keys), 4)
    all_scores["overall"] = overall

    failed = event_assertions + [
        f"ROUTING:{k}={v}" for k, v in routing_scores.items() if v < 1.0
    ] + [
        f"CONFLICT:{k}={v}" for k, v in conflict_scores.items() if v < 1.0
    ] + ([f"POLICY:safety={safety}"] if safety < 1.0 else []) + \
    ([f"WORKFLOW:{workflow}"] if workflow < 1.0 else []) + \
    ([f"OUTPUT:{output_struct}"] if output_struct < 1.0 else [])

    # Build structured diagnostics with classification
    diagnostics: dict = {}
    if routing_scores.get("requiredAgentRecall", 1.0) < 1.0:
        required_set = set(case.expected.routing.requiredAgents)
        selected_set = set(actual.get("selectedAgents", []))
        diagnostics["routing"] = {
            "requiredAgents": sorted(required_set),
            "actualAgents": sorted(selected_set),
            "missingAgents": sorted(required_set - selected_set),
            "extraAgents": sorted(selected_set - required_set),
        }
        diagnostics["classification"] = {"type": "production_capability_gap",
            "reason": f"Missing required agent(s): {', '.join(sorted(required_set - selected_set))}"}
    elif safety < 1.0 and case.expected.policy.requiresHumanReview is not None:
        diagnostics["classification"] = {"type": "dataset_label_bug",
            "reason": f"requiresHumanReview expected={case.expected.policy.requiresHumanReview}, actual={actual.get('policy',{}).get('requiresHumanReview')}"}
    elif any("SYSTEM_ERROR" in str(f) for f in failed):
        diagnostics["classification"] = {"type": "production_capability_gap",
            "reason": "System error during evaluation"}

    return CaseScore(caseId=case.caseId, name=case.name, passed=len(failed) == 0,
                     scores=all_scores, failedAssertions=failed, diagnostics=diagnostics)
