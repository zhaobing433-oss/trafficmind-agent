"""Phase 14 Round 2 — Evaluation Framework Tests"""
import json, os, pytest
from backend.evaluation.dataset_loader import load_dataset
from backend.evaluation.scorers import (
    score_event_parsing, score_routing, score_conflict,
    score_safety_policy, score_workflow_invariants, score_output_structure,
)
from backend.evaluation.models import (
    ExpectedEvent, ExpectedRouting, ExpectedConflict,
    ExpectedPolicy, ExpectedWorkflow, ExpectedOutput,
)
from backend.evaluation.regression_gate import check_gate
from backend.evaluation.models import EvalMetrics
from backend.evaluation.runner import run_evaluation


class TestDataset:
    def test_load_valid_dataset(self):
        cases = load_dataset("backend/evaluation_data/trafficmind_eval_v1.json")
        assert len(cases) >= 30

    def test_all_cases_have_ids(self):
        cases = load_dataset("backend/evaluation_data/trafficmind_eval_v1.json")
        for c in cases:
            assert c.caseId, f"Missing caseId"
            assert c.name, f"Missing name for {c.caseId}"

    def test_dataset_schema_valid(self):
        cases = load_dataset("backend/evaluation_data/trafficmind_eval_v1.json")
        for c in cases:
            assert isinstance(c.input, dict)
            assert c.expected is not None


class TestEventScoring:
    def test_exact_string_match(self):
        exp = ExpectedEvent(expectedFields={"eventType": "accident"})
        score, assertions = score_event_parsing(exp, {"eventType": "accident"})
        assert score == 1.0

    def test_mismatch_returns_partial(self):
        exp = ExpectedEvent(expectedFields={"eventType": "accident", "roadName": "A"})
        score, _ = score_event_parsing(exp, {"eventType": "congestion", "roadName": "A"})
        assert score == 0.5

    def test_numeric_tolerance(self):
        exp = ExpectedEvent(expectedFields={"avgSpeed": 15}, numericTolerance={"avgSpeed": 5.0})
        score, _ = score_event_parsing(exp, {"avgSpeed": 18.0})
        assert score == 1.0

    def test_numeric_outside_tolerance(self):
        exp = ExpectedEvent(expectedFields={"avgSpeed": 15}, numericTolerance={"avgSpeed": 2.0})
        score, _ = score_event_parsing(exp, {"avgSpeed": 20.0})
        assert score == 0.0

    def test_boolean_field(self):
        exp = ExpectedEvent(booleanFields={"simulated": True})
        score, _ = score_event_parsing(exp, {"simulated": True})
        assert score == 1.0


class TestRoutingScoring:
    def test_required_agent_recall_full(self):
        exp = ExpectedRouting(requiredAgents=["CongestionAgent"])
        scores = score_routing(exp, ["CongestionAgent", "DispatchAgent"])
        assert scores["requiredAgentRecall"] == 1.0

    def test_required_agent_missing(self):
        exp = ExpectedRouting(requiredAgents=["CongestionAgent", "AccidentAgent"])
        scores = score_routing(exp, ["CongestionAgent"])
        assert scores["requiredAgentRecall"] == 0.5

    def test_forbidden_agent_detected(self):
        exp = ExpectedRouting(forbiddenAgents=["AccidentAgent"])
        scores = score_routing(exp, ["CongestionAgent", "AccidentAgent"])
        assert scores["forbiddenAgentRate"] > 0

    def test_exact_match_with_forbidden(self):
        exp = ExpectedRouting(requiredAgents=["CongestionAgent"], forbiddenAgents=["AccidentAgent"])
        scores = score_routing(exp, ["CongestionAgent", "DispatchAgent"])
        assert scores["agentExactMatch"] == 1.0


class TestConflictScoring:
    def test_conflict_required_and_present(self):
        exp = ExpectedConflict(required=True)
        scores = score_conflict(exp, [{"type": "signal_vs_safety"}])
        assert scores["conflictRequiredMatch"] == 1.0

    def test_conflict_required_but_missing(self):
        exp = ExpectedConflict(required=True)
        scores = score_conflict(exp, [])
        assert scores["conflictRequiredMatch"] == 0.0


class TestSafetyScoring:
    def test_requires_human_review_match(self):
        exp = ExpectedPolicy(requiresHumanReview=True)
        score = score_safety_policy(exp, {"requiresHumanReview": True})
        assert score == 1.0

    def test_requires_human_review_mismatch(self):
        exp = ExpectedPolicy(requiresHumanReview=False)
        score = score_safety_policy(exp, {"requiresHumanReview": True})
        assert score == 0.0


class TestWorkflowScoring:
    def test_required_nodes(self):
        exp = ExpectedWorkflow(requiredNodes=["trigger", "close"])
        score = score_workflow_invariants(exp, {"state": "trigger validate close"})
        assert score == 1.0


class TestOutputScoring:
    def test_required_fields_present(self):
        exp = ExpectedOutput(requiredFields=["finalDecision", "selectedAgents"])
        score = score_output_structure(exp, {"finalDecision": "ok", "selectedAgents": ["A"]})
        assert score == 1.0

    def test_missing_fields(self):
        exp = ExpectedOutput(requiredFields=["finalDecision", "missingField"])
        score = score_output_structure(exp, {"finalDecision": "ok"})
        assert score == 0.5


class TestRegressionGate:
    def test_pass_threshold(self):
        m = EvalMetrics(overallScore=0.90, requiredAgentRecall=0.95, eventFieldAccuracy=0.90,
                        safetyPolicyPassRate=1.0, workflowInvariantPassRate=1.0,
                        outputStructurePassRate=0.95, conflictF1=0.90)
        result = check_gate(m)
        assert result["passed"], f"Expected PASS, got {result}"

    def test_fail_overall(self):
        m = EvalMetrics(overallScore=0.30, requiredAgentRecall=0.95, eventFieldAccuracy=0.90,
                        safetyPolicyPassRate=1.0, workflowInvariantPassRate=1.0,
                        outputStructurePassRate=0.95, conflictF1=0.90)
        result = check_gate(m)
        assert not result["passed"], "Overall below threshold should FAIL"

    def test_hard_gate_blocks_pass(self):
        m = EvalMetrics(overallScore=0.90, requiredAgentRecall=0.95, eventFieldAccuracy=0.90,
                        safetyPolicyPassRate=1.0, workflowInvariantPassRate=0.5,
                        outputStructurePassRate=0.95, conflictF1=0.90)
        result = check_gate(m)
        assert not result["passed"], "Hard gate (workflow) must override overall"


class TestFullRunner:
    def test_runner_produces_report(self):
        report = run_evaluation("backend/evaluation_data/trafficmind_eval_v1.json", case_id="C01")
        assert report.metrics.totalCases == 1
        assert len(report.caseResults) == 1

    def test_runner_single_category(self):
        report = run_evaluation("backend/evaluation_data/trafficmind_eval_v1.json", category="accident")
        assert report.metrics.totalCases >= 1

    def test_runner_deterministic_repeatable(self):
        r1 = run_evaluation("backend/evaluation_data/trafficmind_eval_v1.json", case_id="C01")
        r2 = run_evaluation("backend/evaluation_data/trafficmind_eval_v1.json", case_id="C01")
        assert r1.metrics.overallScore == r2.metrics.overallScore

    def test_runner_does_not_mutate_db(self):
        import sqlite3
        c = __import__('backend.config', fromlist=['config'])
        conn = sqlite3.connect(c.DB_PATH)
        before = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        conn.close()
        run_evaluation("backend/evaluation_data/trafficmind_eval_v1.json", case_id="C01")
        conn = sqlite3.connect(c.DB_PATH)
        after = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        conn.close()
        assert before == after, f"DB mutated: {before} -> {after}"


class TestJsonReport:
    def test_report_written(self):
        report = run_evaluation("backend/evaluation_data/trafficmind_eval_v1.json", case_id="C01")
        from backend.evaluation.report import generate_reports
        jp, mp = generate_reports(report, "artifacts/evaluation")
        assert os.path.exists(jp)
        assert os.path.exists(mp)
