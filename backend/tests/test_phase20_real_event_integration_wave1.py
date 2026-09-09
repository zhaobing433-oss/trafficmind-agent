"""Phase20 real-event production integration wave1 tests.

All tests use an isolated tmp SQLite DB. They must not touch trafficmind.db.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
import backend.agent.collaboration.db_repository as collab_repo_mod
import backend.chat.chat_db as chat_db
import backend.tools.db_tools as db_tools
from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
from backend.agent.collaboration.event_parser import build_current_event
from backend.agent.multi_agent import _get_event_info
from backend.planning.adapter import plan_to_definition
from backend.planning.models import GoalType, Plan, PlanDefinitionStatus, PlanStep, compute_fingerprint
from backend.workflow.models import NodeType, WorkflowRunStatus
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "phase20_real_event_wave1.db")
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


def _seed_event(event_id="E_REAL_A", status="待派单", road="人民路", event_type="congestion"):
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": event_type,
            "eventTypeCn": "拥堵" if event_type == "congestion" else "事故",
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


def _seed_collaboration_run(
    event_id="E_REAL_A",
    session_id="sess_real_A",
    run_id="run_real_A",
    proposed_actions=None,
    suggestion="建议通知相关部门",
):
    repo = SQLiteCollaborationRepository()
    repo.save_run({
        "run_id": run_id,
        "session_id": session_id,
        "trace_id": f"trace_{run_id}",
        "status": "completed",
        "normalized_event": {
            "eventId": event_id,
            "eventType": "拥堵",
            "eventTypeCn": "拥堵",
            "roadName": "人民路",
            "avgSpeed": 8,
            "queueLength": 220,
            "duration": 1200,
            "riskScore": 100,
            "riskLevel": "重大风险",
            "status": "待派单",
        },
        "selected_agents": ["CongestionAgent", "DispatchAgent"],
        "final_decision": {"fusionSummary": "结构化协同完成", "confidence": 0.8},
    })
    repo.save_task(run_id, {
        "task_id": "task_congestion",
        "agent_name": "CongestionAgent",
        "task_type": "analyze",
        "status": "succeeded",
        "output_snapshot": {
            "agent_name": "CongestionAgent",
            "task_id": "task_congestion",
            "findings": ["平均车速仅 8 km/h，严重拥堵"],
            "confidence": 0.88,
            "suggestion": suggestion,
            "urgency": "high",
            "proposed_actions": proposed_actions or [],
            "evidence_refs": ["doc_rule_1"],
        },
    })
    return repo


def _workflow_client(wf_repo, monkeypatch):
    import backend.workflow.api as workflow_api
    monkeypatch.setattr(workflow_api, "_repo", wf_repo)
    app = FastAPI()
    app.include_router(workflow_api.router)
    return TestClient(app)


class TestEventIdentitySpine:
    def test_collaboration_event_identity_is_preserved(self):
        _seed_event()
        current = build_current_event({}, {"eventId": "E_REAL_A", "roadName": "stale"}, "fresh_event")
        assert current["eventId"] == "E_REAL_A"
        info = _get_event_info({"eventId": "E_REAL_A", "eventType": "congestion", "roadName": "人民路"})
        assert info["eventId"] == "E_REAL_A"

        repo = _seed_collaboration_run()
        run = repo.get_run("run_real_A")
        normalized = json.loads(run["normalized_event"])
        assert normalized["eventId"] == "E_REAL_A"

    def test_event_bound_session_accepts_same_event_and_blocks_cross_event(self):
        _seed_event("E_REAL_A")
        _seed_event("E_REAL_B", road="解放路")
        _seed_collaboration_run(event_id="E_REAL_A", session_id="sess_bound", run_id="run_bound")

        import backend.app as app_mod
        ok = app_mod._prepare_event_bound_stream(app_mod.RoutedStreamRequest(
            sessionId="sess_bound",
            content="继续研判",
            eventId="E_REAL_A",
        ))
        assert ok["eventId"] == "E_REAL_A"

        with pytest.raises(HTTPException) as exc:
            app_mod._prepare_event_bound_stream(app_mod.RoutedStreamRequest(
                sessionId="sess_bound",
                content="错误切换",
                eventId="E_REAL_B",
            ))
        assert exc.value.status_code == 409

    def test_missing_and_invalid_event_id_do_not_create_fake_binding(self):
        import backend.app as app_mod
        assert app_mod._prepare_event_bound_stream(app_mod.RoutedStreamRequest(content="legacy")) is None

        with pytest.raises(HTTPException) as exc:
            app_mod._prepare_event_bound_stream(app_mod.RoutedStreamRequest(eventId="E_MISSING"))
        assert exc.value.status_code == 404

        conn = sqlite3.connect(cfg.DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM collaboration_runs").fetchone()[0]
        conn.close()
        assert count == 0


class TestAgentPlanningAdapter:
    def test_adapter_maps_structured_agent_output_and_audits_rejections(self):
        _seed_event()
        _seed_collaboration_run(proposed_actions=[
            {"actionType": "notify_dingtalk"},
            {"actionType": "simulation_traffic_diversion", "params": {"source_road_id": "r1"}},
            {"actionType": "unknown_tool"},
            "notify_wechat",
        ])

        from backend.planning.agent_planning_adapter import build_planning_input_from_agent
        planning_input = build_planning_input_from_agent("E_REAL_A", "sess_real_A", "run_real_A")
        data = planning_input.to_request_dict()

        assert data["event"]["eventId"] == "E_REAL_A"
        assert data["ragEvidence"]["results"] == [{"id": "doc_rule_1", "source": "agent_evidence_ref"}]
        audit = data["constraints"]["agentRecommendationAudit"]
        assert [a["actionType"] for a in audit["accepted"]] == ["notify_dingtalk"]
        rejected = {(r.get("actionType"), r["reason"]) for r in audit["rejected"]}
        assert ("simulation_traffic_diversion", "simulation_only") in rejected
        assert ("unknown_tool", "not_registered") in rejected
        assert any(r["reason"] == "invalid_structure" for r in audit["rejected"])
        assert not any(a["actionType"] == "notify_wechat" for a in audit["accepted"])

    def test_unbound_collaboration_run_cannot_create_event_plan(self):
        _seed_event()
        repo = SQLiteCollaborationRepository()
        repo.save_run({
            "run_id": "run_legacy",
            "session_id": "sess_legacy",
            "trace_id": "trace_legacy",
            "status": "completed",
            "normalized_event": {"roadName": "人民路"},
            "selected_agents": ["CongestionAgent"],
            "final_decision": {},
        })

        from backend.planning.agent_planning_adapter import (
            AgentPlanningAdapterError,
            build_planning_input_from_agent,
        )
        with pytest.raises(AgentPlanningAdapterError) as exc:
            build_planning_input_from_agent("E_REAL_A", "sess_legacy", "run_legacy")
        assert exc.value.code == "collaboration_run_unbound"

    def test_create_plan_from_agent_persists_event_metadata_and_action_step(self, planning_client, wf_repo):
        _seed_event()
        _seed_collaboration_run(proposed_actions=[{"actionType": "notify_dingtalk"}])

        resp = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_real_A",
            "collaborationRunId": "run_real_A",
        })
        assert resp.status_code == 200
        body = resp.json()
        plan = body["plan"]
        assert plan["eventId"] == "E_REAL_A"
        assert plan["metadata"]["eventSnapshot"]["eventId"] == "E_REAL_A"
        assert plan["metadata"]["sourceAgent"]["collaborationRunId"] == "run_real_A"
        assert [a["actionType"] for a in body["agentRecommendationAudit"]["accepted"]] == ["notify_dingtalk"]
        assert any(s["actionType"] == "notify_dingtalk" for s in plan["steps"])

        definition = wf_repo.get_definition(body["planId"])
        assert definition.metadata["plan"]["eventId"] == "E_REAL_A"
        assert definition.metadata["plan"]["metadata"]["eventSnapshot"]["eventId"] == "E_REAL_A"

    def test_create_plan_from_agent_rejects_non_deterministic_mode(self, planning_client):
        _seed_event()
        _seed_collaboration_run(proposed_actions=[{"actionType": "notify_dingtalk"}])

        resp = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_real_A",
            "collaborationRunId": "run_real_A",
            "plannerMode": "llm",
        })
        assert resp.status_code == 400


class TestWorkflowEventPropagation:
    def test_plan_run_hydrates_event_without_body_and_query_works(self, planning_client, wf_repo, monkeypatch):
        _seed_event()
        _seed_collaboration_run(proposed_actions=[{"actionType": "notify_dingtalk"}])
        created = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_real_A",
            "collaborationRunId": "run_real_A",
        }).json()

        import backend.planning.api as planning_api
        definition = wf_repo.get_definition(created["planId"])
        plan = planning_api._load_plan_from_metadata(definition.metadata)
        body = planning_api.PlanRunRequest(event={}, sessionId="sess_real_A", triggeredBy="test")
        initial_event = planning_api._resolve_plan_run_event(plan, body)
        assert initial_event["eventId"] == "E_REAL_A"
        assert initial_event["roadName"] == "人民路"

        run_id = planning_api._create_planning_run_record(created["planId"], body, initial_event=initial_event)
        run = wf_repo.get_run(run_id)
        assert run.state["currentEvent"]["eventId"] == "E_REAL_A"

        client = _workflow_client(wf_repo, monkeypatch)
        resp = client.get("/workflow/runs?event_id=E_REAL_A&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["runs"][0]["runId"] == run_id

    def test_client_snapshot_stale_db_wins_and_event_id_mismatch_rejected(self, planning_client, wf_repo):
        _seed_event()
        _seed_event("E_REAL_B", road="解放路")
        _seed_collaboration_run()
        created = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_real_A",
            "collaborationRunId": "run_real_A",
        }).json()

        import backend.planning.api as planning_api
        definition = wf_repo.get_definition(created["planId"])
        plan = planning_api._load_plan_from_metadata(definition.metadata)

        stale = planning_api.PlanRunRequest(event={"eventId": "E_REAL_A", "roadName": "旧路"})
        initial_event = planning_api._resolve_plan_run_event(plan, stale)
        assert initial_event["roadName"] == "人民路"

        mismatch = planning_api.PlanRunRequest(event={"eventId": "E_REAL_B"})
        with pytest.raises(HTTPException) as exc:
            planning_api._resolve_plan_run_event(plan, mismatch)
        assert exc.value.status_code == 409

    def test_legacy_plan_without_event_id_creates_no_fake_event_relation(self, wf_repo, monkeypatch):
        _seed_event()
        plan = Plan(
            planId="plan_legacy",
            planFingerprint="fp_legacy",
            goal="legacy",
            goalType=GoalType.GENERIC,
            definitionStatus=PlanDefinitionStatus.ACTIVE,
            version=1,
            steps=[
                PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
                PlanStep(stepId="close", stepType=NodeType.CLOSE),
            ],
        )
        plan.planFingerprint = compute_fingerprint(plan.steps)
        wf_repo.save_definition(plan_to_definition(plan))

        import backend.planning.api as planning_api
        body = planning_api.PlanRunRequest(event={"eventId": "E_REAL_A", "roadName": "人民路"})
        initial_event = planning_api._resolve_plan_run_event(plan, body)
        assert "eventId" not in initial_event
        run_id = planning_api._create_planning_run_record("plan_legacy", body, initial_event=initial_event)
        assert wf_repo.get_run(run_id).state["currentEvent"].get("eventId") is None

        client = _workflow_client(wf_repo, monkeypatch)
        assert client.get("/workflow/runs?event_id=E_REAL_A").json()["total"] == 0

    def test_terminal_event_rejects_workflow_execution(self, planning_client, wf_repo):
        _seed_event(status="已处置")
        _seed_collaboration_run()
        created = planning_client.post("/planning/plans/from-agent", json={
            "eventId": "E_REAL_A",
            "sessionId": "sess_real_A",
            "collaborationRunId": "run_real_A",
        }).json()

        import backend.planning.api as planning_api
        definition = wf_repo.get_definition(created["planId"])
        plan = planning_api._load_plan_from_metadata(definition.metadata)
        with pytest.raises(HTTPException) as exc:
            planning_api._resolve_plan_run_event(plan, planning_api.PlanRunRequest(event={}))
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "event_terminal"
