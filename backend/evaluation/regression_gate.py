"""Regression Gate — hard thresholds that must pass.

Gate fails closed: missing required metrics → FAIL.
"""
from typing import Dict, Any
from backend.evaluation.models import EvalMetrics

# All metrics that must be present for a valid gate result
REQUIRED_METRICS = [
    "overall", "eventFieldAccuracy", "requiredAgentRecall",
    "conflictF1", "safetyPolicyPassRate",
    "workflowInvariantPassRate", "outputStructurePassRate",
]

# Thresholds — any metric below its threshold → gate FAIL
# Hard gates: safety and workflow invariants must be 100%
REGRESSION_GATES = {
    "overall": 0.90,
    "eventFieldAccuracy": 0.90,
    "requiredAgentRecall": 0.95,
    "conflictF1": 0.90,
    "safetyPolicyPassRate": 1.0,
    "workflowInvariantPassRate": 1.0,
    "outputStructurePassRate": 0.95,
}

HARD_GATES = {"safetyPolicyPassRate", "workflowInvariantPassRate"}


def check_gate(metrics: EvalMetrics) -> Dict[str, Any]:
    """Evaluate all gates against metrics. Fails closed on missing data."""
    failures = []

    # Map metric object fields to gate keys
    values = {
        "overall": metrics.overallScore,
        "eventFieldAccuracy": metrics.eventFieldAccuracy,
        "requiredAgentRecall": metrics.requiredAgentRecall,
        "conflictF1": metrics.conflictF1,
        "safetyPolicyPassRate": metrics.safetyPolicyPassRate,
        "workflowInvariantPassRate": metrics.workflowInvariantPassRate,
        "outputStructurePassRate": metrics.outputStructurePassRate,
    }

    # Check every required metric exists
    for key in REQUIRED_METRICS:
        if key not in values:
            failures.append({"gate": key, "threshold": REGRESSION_GATES.get(key, 1.0), "actual": "MISSING"})
        elif values[key] is None:
            failures.append({"gate": key, "threshold": REGRESSION_GATES.get(key, 1.0), "actual": "NULL"})

    if any(f.get("actual") in ("MISSING", "NULL") for f in failures):
        return {"passed": False, "failures": failures, "thresholds": dict(REGRESSION_GATES)}

    # Check thresholds
    for key, threshold in REGRESSION_GATES.items():
        actual = values.get(key, 0.0)
        if actual < threshold:
            failures.append({"gate": key, "threshold": threshold, "actual": round(actual, 4)})

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "thresholds": dict(REGRESSION_GATES),
    }
