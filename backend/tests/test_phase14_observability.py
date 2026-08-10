"""Phase 14 Observability Tests"""
import json
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from backend.app import app
    return TestClient(app)

class TestObservabilityAPI:
    def test_completed_workflow_returns_200(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["definition_name"] is not None

    def test_nodes_have_display_names(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        for n in data["nodes"]:
            assert n["display_name"], f"Node {n['node_id']} has no display_name"
            assert n["description"], f"Node {n['node_id']} has no description"

    def test_agent_observation_present(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        assert data["agent"] is not None
        assert data["agent"]["agent_name"] == "CongestionAgent"

    def test_approval_observation_present(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        assert data["approval"] is not None

    def test_action_observation_present(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        assert len(data["actions"]) >= 1

    def test_metrics_computed(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        m = data["metrics"]
        assert m["node_count"] >= 1
        assert "succeeded" in m
        assert "action_count" in m

    def test_node_order_preserved(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        node_ids = [n["node_id"] for n in data["nodes"]]
        assert node_ids[0] == "trigger" or node_ids[0].startswith("trigger")

    def test_invalid_run_404(self, client):
        resp = client.get("/observability/workflows/nonexistent")
        assert resp.status_code == 404

    def test_read_only_no_mutation(self, client):
        resp1 = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        resp2 = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        assert resp1.json() == resp2.json()

    def test_sanitization_forbidden_keys(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        raw = json.dumps(resp.json())
        for key in ["chain_of_thought", "thinking", "system_prompt", "hidden_reasoning"]:
            assert key not in raw, f"Forbidden key '{key}' found in output"

    def test_sanitization_recursive(self):
        from backend.observability.models import sanitize_observability
        data = {"nested": {"thinking": "secret", "safe": "ok"}, "chain_of_thought": "hidden"}
        result = sanitize_observability(data)
        assert "thinking" not in result.get("nested", {})
        assert "chain_of_thought" not in result
        assert result["nested"]["safe"] == "ok"

    def test_node_display_names_all_mapped(self):
        from backend.observability.models import NODE_DISPLAY, NODE_DESCRIPTIONS
        types = ["trigger","validate_event","rule_router","rag_retrieve","memory_context",
                 "agent_task","evidence_evaluate","risk_gate","human_approval","action","close"]
        for t in types:
            assert t in NODE_DISPLAY, f"Missing display name for {t}"
            assert t in NODE_DESCRIPTIONS, f"Missing description for {t}"

    def test_duration_calculation(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        assert isinstance(data["total_duration_ms"], (int, float))

    def test_simulation_refs_present(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        refs = data.get("simulation_refs", {})
        assert "simulationRunId" in refs

    def test_evidence_refs_on_agent(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        if data["agent"]:
            refs = data["agent"].get("evidence_refs", [])
            assert isinstance(refs, list)

    def test_proposed_actions_sanitized(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        if data["agent"]:
            for pa in data["agent"].get("proposed_actions", []):
                assert "chain_of_thought" not in json.dumps(pa)

    def test_retry_info_present(self, client):
        resp = client.get("/observability/workflows/wfrun_20260810022901_0d80c2ec")
        data = resp.json()
        assert "retried" in data["metrics"]

    def test_awaiting_approval_workflow(self, client):
        resp = client.get("/observability/workflows/wfrun_20260809060655_13d80a9c")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_approval" or data["status"] == "completed"
