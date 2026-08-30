"""Phase20 real-event product flow wave2 tests.

All tests use an isolated tmp SQLite DB. They must not touch trafficmind.db.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
import backend.agent.collaboration.db_repository as collab_repo_mod
import backend.chat.chat_db as chat_db
import backend.tools.db_tools as db_tools
from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "phase20_real_event_wave2.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    monkeypatch.setattr(db_tools, "DB_PATH", test_db)
    monkeypatch.setattr(chat_db, "DB_PATH", test_db)
    monkeypatch.setattr(collab_repo_mod, "DB_PATH", test_db)
    chat_db.reset_initialized()
    db_tools.init_db()
    chat_db.init_chat_tables()
    collab_repo_mod.init_collaboration_tables()
    init_workflow_tables()
    yield test_db


@pytest.fixture
def wf_repo(monkeypatch):
    repo = SQLiteWorkflowRepository()
    import backend.planning.api as planning_api
    import backend.workflow.api as workflow_api
    monkeypatch.setattr(planning_api, "_repo", repo)
    monkeypatch.setattr(workflow_api, "_repo", repo)
    return repo


@pytest.fixture
def planning_client(wf_repo):
    import backend.planning.api as planning_api
    app = FastAPI()
    app.include_router(planning_api.router)
    return TestClient(app)


@pytest.fixture
def app_client(wf_repo, monkeypatch):
    import backend.app as app_mod
    import backend.planning.api as planning_api
    import backend.workflow.api as workflow_api
    monkeypatch.setattr(planning_api, "_repo", wf_repo)
    monkeypatch.setattr(workflow_api, "_repo", wf_repo)
    return TestClient(app_mod.app)


def _seed_event(event_id="E_REAL_A", status="待派单", road="人民路"):
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": "congestion",
            "eventTypeCn": "拥堵",
            "roadName": road,
            "direction": "东向西",
            "avgSpeed": 8,
            "queueLength": 220,
            "duration": 1200,
            "weather": "rain",
            "timePeriod": "morning_peak",
            "isMainRoad": True,
            "nearbySchool": False,
            "nearbyHospital": False,
        },
        "riskScore": 100,
        "riskLevel": "重大风险",
        "status": status,
        "report": "fixture",
        "analyzedAt": "2026-08-30 10:00:00",
    })


def _seed_collaboration_run(event_id="E_REAL_A", session_id="sess_real_A", run_id="run_real_A"):
    repo = SQLiteCollaborationRepository()
    repo.save_run({
        "run_id": run_id,
        "session_id": session_id,
        "trace_id": f"trace_{run_id}",
        "status": "completed",
        "normalized_event": {
            "eventId": event_id,
            "eventType": "congestion",
            "eventTypeCn": "拥堵",
            "roadName": "人民路",
            "riskScore": 100,
            "riskLevel": "重大风险",
            "status": "待派单",
        },
        "selected_agents": ["CongestionAgent", "DispatchAgent"],
        "final_decision": {"fusionSummary": "结构化协同完成", "confidence": 0.8},
    })
    repo.save_task(run_id, {
        "task_id": f"task_{run_id}",
        "agent_name": "CongestionAgent",
        "task_type": "analyze",
        "status": "succeeded",
        "output_snapshot": {
            "agent_name": "CongestionAgent",
            "findings": ["平均车速仅 8 km/h，严重拥堵"],
            "confidence": 0.88,
            "suggestion": "建议通知相关部门",
            "urgency": "high",
            "proposed_actions": [{"actionType": "notify_dingtalk"}],
            "evidence_refs": ["doc_rule_1"],
        },
    })
    return repo


class TestWave2ReadApis:
    def test_collaboration_event_filter_is_exact_and_malformed_safe(self, app_client):
        _seed_collaboration_run("E_REAL_A", "sess_a", "run_a")
        _seed_collaboration_run("E_REAL_B", "sess_b", "run_b")
        conn = sqlite3.connect(cfg.DB_PATH)
        conn.execute(
            """
            INSERT INTO collaboration_runs
                (run_id, session_id, trace_id, status, normalized_event,
                 selected_agents, skipped_agents, failed_agents, budget_usage,
                 final_decision, started_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run_malformed", "sess_bad", "trace_bad", "completed", "{bad json",
                "[]", "[]", "[]", "{}", "{}", "2026-08-30T00:00:00",
                "2026-08-30T00:00:01", "",
            ),
        )
        conn.commit()
        conn.close()

        resp = app_client.get("/collaboration/runs?event_id=E_REAL_A&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert [r["run_id"] for r in body["runs"]] == ["run_a"]
        assert body["runs"][0]["normalized_event"]["eventId"] == "E_REAL_A"

    def test_plan_list_event_filter_returns_only_event_bound_plans(self, planning_client):
        _seed_event("E_REAL_A")
        _seed_event("E_REAL_B", road="解放路")
        _seed_collaboration_run("E_REAL_A", "sess_a", "run_a")
        _seed_collaboration_run("E_REAL_B", "sess_b", "run_b")

        created_a = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_a",
            "collaborationRunId": "run_a",
        })
        created_b = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_B",
            "sessionId": "sess_b",
            "collaborationRunId": "run_b",
        })
        assert created_a.status_code == 200
        assert created_b.status_code == 200

        resp = planning_client.get("/planning/plans?eventId=E_REAL_A&pageSize=20")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["plans"][0]["planId"] == created_a.json()["planId"]
        assert body["plans"][0]["eventId"] == "E_REAL_A"

    def test_planning_event_filter_ignores_malformed_metadata(self, planning_client):
        _seed_event("E_REAL_A")
        _seed_collaboration_run("E_REAL_A", "sess_a", "run_a")
        created = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_a",
            "collaborationRunId": "run_a",
        })
        assert created.status_code == 200

        conn = sqlite3.connect(cfg.DB_PATH)
        conn.execute(
            """
            INSERT INTO workflow_definitions
                (id, name, description, category, status, nodes_json, entry_node_id, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "plan_malformed", "broken", "", "planning", "active", "[]", "",
                '{"planFingerprint": "fp", "plan": ', "2026-08-30T00:00:00Z", "2026-08-30T00:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

        resp = planning_client.get("/planning/plans?eventId=E_REAL_A")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_event_id_alias_still_uses_authoritative_event_binding(self):
        _seed_event("E_REAL_A")
        import backend.app as app_mod

        snapshot = app_mod._prepare_event_bound_stream(app_mod.RoutedStreamRequest(
            content="使用 legacy event_id alias",
            event_id="E_REAL_A",
        ))

        assert snapshot["eventId"] == "E_REAL_A"
        assert snapshot["roadName"] == "人民路"
