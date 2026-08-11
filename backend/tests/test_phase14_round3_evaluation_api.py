"""Phase 14 Round 3 — Evaluation API Tests"""
import json, os, pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from backend.app import app
    return TestClient(app)

class TestReportList:
    def test_list_reports_200(self, client):
        resp = client.get("/evaluation/reports?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "reports" in data
        assert len(data["reports"]) <= 5

    def test_reports_newest_first(self, client):
        resp = client.get("/evaluation/reports?limit=10")
        data = resp.json()
        if len(data["reports"]) >= 2:
            r0 = data["reports"][0]["reportId"]
            r1 = data["reports"][1]["reportId"]
            assert r0 > r1, "Reports should be newest first"

    def test_limit_respected(self, client):
        resp = client.get("/evaluation/reports?limit=2")
        assert len(resp.json()["reports"]) <= 2

class TestReportDetail:
    def test_valid_report_200(self, client):
        resp = client.get("/evaluation/reports?limit=1")
        ids = [r["reportId"] for r in resp.json()["reports"]]
        if not ids: pytest.skip("No reports available")
        resp2 = client.get(f"/evaluation/reports/{ids[0]}")
        assert resp2.status_code == 200

    def test_invalid_report_404(self, client):
        resp = client.get("/evaluation/reports/eval_report_99999999_999999")
        assert resp.status_code == 404

    def test_dot_dot_path_blocked(self, client):
        resp = client.get("/evaluation/reports/../etc/passwd")
        assert resp.status_code == 404

    def test_absolute_path_blocked(self, client):
        resp = client.get("/evaluation/reports/C:/windows/system32")
        assert resp.status_code == 404

    def test_empty_string_is_list(self, client):
        resp = client.get("/evaluation/reports/")
        assert resp.status_code == 200  # empty path routes to list endpoint

class TestCaseDetail:
    def test_valid_case(self, client):
        resp = client.get("/evaluation/reports?limit=1")
        ids = [r["reportId"] for r in resp.json()["reports"]]
        if not ids: pytest.skip("No reports")
        report = client.get(f"/evaluation/reports/{ids[0]}").json()
        cases = report.get("caseResults", [])
        if not cases: pytest.skip("No cases")
        cid = cases[0]["caseId"]
        resp2 = client.get(f"/evaluation/reports/{ids[0]}/cases/{cid}")
        assert resp2.status_code == 200
        assert resp2.json()["caseId"] == cid

    def test_invalid_case_404(self, client):
        resp = client.get("/evaluation/reports?limit=1")
        ids = [r["reportId"] for r in resp.json()["reports"]]
        if not ids: pytest.skip("No reports")
        resp2 = client.get(f"/evaluation/reports/{ids[0]}/cases/NONEXISTENT")
        assert resp2.status_code == 404

class TestCompare:
    def test_compare_two_reports(self, client):
        resp = client.get("/evaluation/reports?limit=5")
        reports = resp.json()["reports"]
        if len(reports) < 2: pytest.skip("Need 2+ reports")
        base = reports[1]["reportId"]
        target = reports[0]["reportId"]
        resp2 = client.get(f"/evaluation/compare?base={base}&target={target}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert "metricsDelta" in data
        assert len(data["metricsDelta"]) > 0

    def test_compare_percentage_points(self, client):
        """Delta must be in percentage points, target - base."""
        resp = client.get("/evaluation/reports?limit=5")
        reports = resp.json()["reports"]
        if len(reports) < 2: pytest.skip("Need 2+ reports")
        base = reports[1]["reportId"]
        target = reports[0]["reportId"]
        data = client.get(f"/evaluation/compare?base={base}&target={target}").json()
        for d in data["metricsDelta"]:
            # percentagePoints = (target - base) * 100
            expected_pp = round((d["target"] - d["base"]) * 100, 2)
            assert d["percentagePoints"] == expected_pp, f"{d['metric']}: pp mismatch"

    def test_compare_direction(self, client):
        resp = client.get("/evaluation/reports?limit=5")
        reports = resp.json()["reports"]
        if len(reports) < 2: pytest.skip("Need 2+ reports")
        data = client.get(f"/evaluation/compare?base={reports[1]['reportId']}&target={reports[0]['reportId']}").json()
        for d in data["metricsDelta"]:
            if d["delta"] > 0: assert d["status"] == "improved"
            elif d["delta"] < 0: assert d["status"] == "regressed"
            else: assert d["status"] == "unchanged"

    def test_compare_missing_report(self, client):
        resp = client.get("/evaluation/compare?base=nonexistent&target=also_nonexistent")
        assert resp.status_code == 404

class TestSanitization:
    def test_forbidden_keys_removed(self, client):
        """Create a test artifact with forbidden keys and verify removal."""
        test_id = "eval_report_99999999_999999_test"
        test_path = os.path.join("artifacts", "evaluation", f"{test_id}.json")
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        data = {
            "metadata": {"generatedAt": "test", "datasetVersion": "v99"},
            "metrics": {"totalCases": 1, "overallScore": 1.0},
            "regressionGate": {"passed": True, "failures": [], "thresholds": {}},
            "caseResults": [{"caseId": "T01", "chain_of_thought": "secret", "thinking": "hidden", "system_prompt": "prompt", "safe_data": "ok"}],
        }
        with open(test_path, "w") as f: json.dump(data, f)
        try:
            resp = client.get(f"/evaluation/reports/{test_id}")
            if resp.status_code == 200:
                body = resp.json()
                raw = json.dumps(body)
                for key in ["chain_of_thought", "thinking", "system_prompt"]:
                    assert key not in raw, f"Forbidden key '{key}' found in response"
                # safe_data should still be there
                assert "safe_data" in raw
        finally:
            os.remove(test_path)

    def test_case_endpoint_sanitized(self, client):
        test_id = "eval_report_99999999_999999_test2"
        test_path = os.path.join("artifacts", "evaluation", f"{test_id}.json")
        data = {
            "metadata": {"generatedAt": "test"}, "metrics": {"totalCases": 1, "overallScore": 1.0},
            "regressionGate": {"passed": True, "failures": [], "thresholds": {}},
            "caseResults": [{"caseId": "T02", "chain_of_thought": "hidden"}],
        }
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        with open(test_path, "w") as f: json.dump(data, f)
        try:
            resp = client.get(f"/evaluation/reports/{test_id}/cases/T02")
            if resp.status_code == 200:
                assert "chain_of_thought" not in json.dumps(resp.json())
        finally:
            os.remove(test_path)


class TestReadOnlyIntegrity:
    def test_no_side_effects_from_api_calls(self, client):
        import sqlite3, backend.config as cfg
        conn = sqlite3.connect(cfg.DB_PATH)
        before_sessions = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
        before_runs = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        before_events = conn.execute("SELECT COUNT(*) FROM workflow_events").fetchone()[0]
        conn.close()

        # Multiple API calls
        for _ in range(5):
            client.get("/evaluation/reports?limit=5")
        resp = client.get("/evaluation/reports?limit=1")
        ids = [r["reportId"] for r in resp.json().get("reports", [])]
        if ids:
            for _ in range(3):
                client.get(f"/evaluation/reports/{ids[0]}")
                if len(ids) >= 2:
                    client.get(f"/evaluation/compare?base={ids[1]}&target={ids[0]}")

        conn = sqlite3.connect(cfg.DB_PATH)
        after_sessions = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
        after_runs = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        after_events = conn.execute("SELECT COUNT(*) FROM workflow_events").fetchone()[0]
        conn.close()

        assert before_sessions == after_sessions, f"Sessions changed: {before_sessions} -> {after_sessions}"
        assert before_runs == after_runs, f"Workflow runs changed: {before_runs} -> {after_runs}"
        assert before_events == after_events, f"Events changed: {before_events} -> {after_events}"
