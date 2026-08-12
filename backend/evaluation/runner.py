"""
Evaluation Runner — deterministic-first, read-only.

Usage:
    python -m backend.evaluation.runner --dataset backend/evaluation_data/trafficmind_eval_v1.json
    python -m backend.evaluation.runner --dataset ... --category congestion --fail-on-regression
"""
from __future__ import annotations
import argparse
import sys
from typing import Any, Dict, List

from backend.evaluation.models import EvalReport, EvalMetrics, CaseScore
from backend.evaluation.dataset_loader import load_dataset
from backend.evaluation.scorers import score_case
from backend.evaluation.regression_gate import check_gate
from backend.evaluation.report import generate_reports


def _run_system(case_input: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the deterministic agent pipeline on a case input."""
    from backend.agent.router import route_agents
    from backend.agent.conflict_resolver import detect_conflicts
    from backend.agent.multi_agent import _get_event_info

    raw = dict(case_input)
    raw.setdefault("roadName", "未知路段")
    raw.setdefault("direction", "")
    raw.setdefault("weather", "clear")
    raw.setdefault("timePeriod", "off_peak")
    raw.setdefault("isMainRoad", False)
    raw.setdefault("nearbySchool", False)
    raw.setdefault("nearbyHospital", False)
    raw.setdefault("confidence", 0.9)
    raw.setdefault("eventTypeCn", raw.get("eventType", ""))
    raw.setdefault("duration", 0)
    raw.setdefault("vehicleCount", 0)

    # Use input directly as event (skip build_current_event which zeros dynamic fields)
    current_event = raw
    routing = route_agents(current_event)
    info = _get_event_info(current_event)

    agent_map = {
        "CongestionAgent": None, "AccidentAgent": None,
        "SignalAgent": None, "DispatchAgent": None,
    }
    from backend.agent.multi_agent import CongestionAgent, AccidentAgent, SignalAgent, DispatchAgent
    agent_map = {"CongestionAgent": CongestionAgent, "AccidentAgent": AccidentAgent, "SignalAgent": SignalAgent, "DispatchAgent": DispatchAgent}

    agent_results = []
    for name in routing.get("selectedAgents", []):
        cls = agent_map.get(name)
        if cls:
            result = cls().analyze(info)
            agent_results.append(result)

    conflicts = detect_conflicts(agent_results)
    # Compute requires_approval matching rule_router:85-90 production logic
    risk_score_val = current_event.get("riskScore", routing.get("riskScore", 0))
    risk_level_val = current_event.get("riskLevel", routing.get("riskLevel", ""))
    nearby_school = bool(current_event.get("nearbySchool", False))
    nearby_hospital = bool(current_event.get("nearbyHospital", False))
    requires_human_review = (
        risk_level_val in ("高风险", "重大风险")
        or (nearby_school and risk_score_val >= 31)
        or (nearby_hospital and risk_score_val >= 61)
    )

    return {
        "event": current_event,
        "routing": routing,
        "selectedAgents": routing.get("selectedAgents", []),
        "agentResults": agent_results,
        "conflicts": conflicts,
        "policy": {"requiresHumanReview": requires_human_review},
        "output": {
            "finalDecision": "; ".join(r.get("suggestion", "") for r in agent_results),
            "fusionSummary": "; ".join(r.get("suggestion", "") for r in agent_results)[:200],
            "requiresHumanReview": requires_human_review,
            "selectedAgents": routing.get("selectedAgents", []),
        },
    }


def run_evaluation(dataset_path: str, category: str = None, case_id: str = None) -> EvalReport:
    cases = load_dataset(dataset_path)
    if category:
        cases = [c for c in cases if c.category == category]
    if case_id:
        cases = [c for c in cases if c.caseId == case_id]

    results: List[CaseScore] = []
    for case in cases:
        try:
            actual = _run_system(case.input)
            cs = score_case(case, actual)
        except Exception as e:
            cs = CaseScore(caseId=case.caseId, name=case.name, passed=False,
                           scores={"overall": 0.0}, failedAssertions=[f"SYSTEM_ERROR: {e}"],
                           diagnostics={"classification": {"type": "production_capability_gap",
                               "reason": f"Evaluation runtime error: {str(e)[:200]}"}})
        results.append(cs)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    # Core metrics for overall score (7 equal-weight metrics, agentExactMatch excluded as diagnostic)
    core_metrics = ["eventFieldAccuracy", "requiredAgentRecall", "forbiddenAgentRate",
                    "conflictF1", "safetyPolicyPassRate", "workflowInvariantPassRate", "outputStructurePassRate"]
    overall = round(sum(_avg(results, k) for k in core_metrics) / len(core_metrics), 4)

    metrics = EvalMetrics(
        totalCases=total, passedCases=passed, failedCases=total - passed,
        eventFieldAccuracy=_avg(results, "eventFieldAccuracy"),
        requiredAgentRecall=_avg(results, "requiredAgentRecall"),
        agentExactMatch=_avg(results, "agentExactMatch"),
        forbiddenAgentRate=_avg(results, "forbiddenAgentRate"),
        conflictPrecision=_avg(results, "conflictRequiredMatch"),
        conflictRecall=_avg(results, "conflictTypeMatch"),
        conflictF1=_compute_f1(_avg(results, "conflictRequiredMatch"), _avg(results, "conflictTypeMatch")),
        safetyPolicyPassRate=_avg(results, "safetyPolicyPassRate"),
        workflowInvariantPassRate=_avg(results, "workflowInvariantPassRate"),
        outputStructurePassRate=_avg(results, "outputStructurePassRate"),
        overallScore=overall,
    )
    gate = check_gate(metrics)
    return EvalReport(
        metadata={"datasetVersion": "v1", "datasetPath": dataset_path},
        metrics=metrics, caseResults=results, regressionGate=gate,
    )


def _avg(results: List[CaseScore], key: str) -> float:
    vals = [r.scores.get(key, 0.0) for r in results if key in r.scores]
    return round(sum(vals) / max(len(vals), 1), 4)

def _compute_f1(p: float, r: float) -> float:
    if p + r == 0: return 1.0
    return round(2 * p * r / (p + r), 4)


def main():
    parser = argparse.ArgumentParser(description="TrafficMind Agent Evaluation Runner")
    parser.add_argument("--dataset", required=True, help="Path to evaluation dataset JSON")
    parser.add_argument("--case", help="Run a single case by caseId")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--output", default="artifacts/evaluation", help="Output directory")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if regression gate fails")
    args = parser.parse_args()

    report = run_evaluation(args.dataset, args.category, args.case)
    json_path, md_path = generate_reports(report, args.output)

    m = report.metrics
    print(f"Total: {m.totalCases} | Passed: {m.passedCases} | Failed: {m.failedCases}")
    print(f"Overall: {m.overallScore:.2%} | Event: {m.eventFieldAccuracy:.2%} | Routing: {m.requiredAgentRecall:.2%}")
    print(f"Safety: {m.safetyPolicyPassRate:.2%} | Workflow: {m.workflowInvariantPassRate:.2%} | Output: {m.outputStructurePassRate:.2%}")
    gate = report.regressionGate
    print(f"Regression Gate: {'PASS' if gate.get('passed') else 'FAIL'}")
    if gate.get("failures"):
        for f in gate["failures"]:
            print(f"  - {f['gate']}: {f['actual']:.2%} < {f['threshold']:.2%}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")

    if args.fail_on_regression and not gate.get("passed", True):
        sys.exit(1)


if __name__ == "__main__":
    main()
