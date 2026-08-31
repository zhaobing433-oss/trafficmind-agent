"""Phase21 Wave E traffic case memory tests.

All tests use isolated temporary SQLite databases and never mutate
backend/data/trafficmind.db.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.agent.collaboration.db_repository as collab_db
import backend.config as cfg
import backend.tools.db_tools as db_tools
from backend.agent.collaboration.db_repository import (
    SQLiteCollaborationRepository,
    init_collaboration_tables,
)
from backend.case_memory.api import router as case_memory_router
from backend.case_memory.models import CaseMemoryError, build_case_id
from backend.case_memory.repository import SQLiteCaseMemoryRepository, init_case_memory_tables
from backend.case_memory.service import TrafficCaseMemoryService
from backend.planning.adapter import plan_to_definition
from backend.planning.models import GoalType, Plan, PlanDefinitionStatus, PlanStep
from backend.regional.repository import SQLiteRegionalRepository
from backend.workflow.models import (
    ActionStatus,
    ApprovalDecision,
    NodeType,
    WorkflowActionRecord,
    WorkflowApproval,
    WorkflowDefinitionVersion,
    WorkflowRun,
    WorkflowRunStatus,
)
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    production_db = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
    test_db = str(tmp_path / "phase21_case_memory.db")
    assert test_db != production_db
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    monkeypatch.setattr(db_tools, "DB_PATH", test_db)
    monkeypatch.setattr(collab_db, "DB_PATH", test_db)
    db_tools.init_db()
    init_workflow_tables()
    init_collaboration_tables()
    regional_repo = SQLiteRegionalRepository(db_path=test_db)
    regional_repo.import_context_pack(_context_pack())
    init_case_memory_tables()
    return {
        "db": test_db,
        "productionDb": production_db,
        "workflowRepo": SQLiteWorkflowRepository(),
        "regionalRepo": regional_repo,
        "collaborationRepo": SQLiteCollaborationRepository(),
        "caseRepo": SQLiteCaseMemoryRepository(),
    }


@pytest.fixture()
def service(isolated):
    return TrafficCaseMemoryService(
        repository=isolated["caseRepo"],
        regional_repo=isolated["regionalRepo"],
    )


@pytest.fixture()
def api_client(isolated):
    app = FastAPI()
    app.include_router(case_memory_router)
    return TestClient(app)


def _context_pack() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_case_memory.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "REGION_A",
            "name": "测试区域A",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {"roadId": "ROAD_A_MAIN", "regionId": "REGION_A", "name": "人民路"},
            {"roadId": "ROAD_A_SIDE", "regionId": "REGION_A", "name": "解放路"},
        ],
        "intersections": [
            {
                "intersectionId": "INT_A_MAIN",
                "regionId": "REGION_A",
                "name": "人民路-解放路路口",
            },
        ],
        "roadRelations": [
            {
                "relationId": "REL_A_MAIN",
                "regionId": "REGION_A",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_A_MAIN",
                "toEntityType": "intersection",
                "toEntityId": "INT_A_MAIN",
                "relationType": "connects",
            },
        ],
        "pois": [],
    }


def _context_pack_b() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_case_memory.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "REGION_B",
            "name": "测试区域B",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {"roadId": "ROAD_B_MAIN", "regionId": "REGION_B", "name": "人民路"},
        ],
        "intersections": [
            {
                "intersectionId": "INT_B_MAIN",
                "regionId": "REGION_B",
                "name": "人民路-学院路路口",
            },
        ],
        "roadRelations": [
            {
                "relationId": "REL_B_MAIN",
                "regionId": "REGION_B",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_B_MAIN",
                "toEntityType": "intersection",
                "toEntityId": "INT_B_MAIN",
                "relationType": "connects",
            },
        ],
        "pois": [],
    }


def _seed_event(
    event_id: str,
    *,
    event_type: str = "congestion",
    road_name: str = "人民路",
    analyzed_at: str = "2026-06-30T08:00:00Z",
) -> None:
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": event_type,
            "eventTypeCn": "拥堵" if event_type == "congestion" else "事故",
            "roadName": road_name,
            "direction": "东向西",
            "avgSpeed": 9,
            "queueLength": 180,
            "duration": 3600,
            "weather": "rain",
            "timePeriod": "peak",
            "debugOnly": "RAW_EVENT_SENTINEL",
        },
        "riskScore": 92,
        "riskLevel": "重大风险",
        "status": "待派单",
        "report": "persisted fixture report",
        "analyzedAt": analyzed_at,
        "debugPayload": "FULL_RESULT_SENTINEL",
    })


def _bind_event(
    regional_repo: SQLiteRegionalRepository,
    event_id: str,
    *,
    region_id: str = "REGION_A",
    road_id: str = "ROAD_A_MAIN",
    intersection_id: str = "INT_A_MAIN",
) -> None:
    regional_repo.save_resolved_event_location_binding({
        "status": "resolved",
        "eventId": event_id,
        "regionId": region_id,
        "roadId": road_id,
        "intersectionId": intersection_id,
        "resolutionMethod": "exact_alias",
        "matchedAlias": "人民路",
    })


def _save_collaboration_chain(
    repo: SQLiteCollaborationRepository,
    *,
    event_id: str,
    collaboration_run_id: str,
    session_id: str,
) -> None:
    repo.save_run({
        "run_id": collaboration_run_id,
        "session_id": session_id,
        "trace_id": f"trace_{collaboration_run_id}",
        "status": "completed",
        "normalized_event": {
            "eventId": event_id,
            "eventType": "congestion",
            "roadName": "人民路",
        },
        "selected_agents": ["CongestionAgent", "DispatchAgent"],
        "failed_agents": [],
        "final_decision": {"summary": "建议先通知值守人员，并观察拥堵回落。"},
        "started_at": "2026-06-30T08:05:00Z",
        "completed_at": "2026-06-30T08:07:00Z",
    })
    repo.save_task(collaboration_run_id, {
        "task_id": "task_congestion",
        "agent_name": "CongestionAgent",
        "task_type": "analysis",
        "status": "succeeded",
        "output_snapshot": {
            "agentName": "CongestionAgent",
            "taskId": "task_congestion",
            "findings": ["排队长度超过阈值"],
            "suggestion": "通知值守人员并持续观察",
            "proposedActions": [
                {"actionType": "notify_wechat", "params": {}},
                {"actionType": "simulation_monitor", "params": {}},
            ],
            "evidenceRefs": [{"docId": "doc_policy", "chunkId": "chunk_1"}],
        },
        "completed_at": "2026-06-30T08:06:00Z",
    })
    repo.save_message({
        "message_id": f"msg_{collaboration_run_id}",
        "run_id": collaboration_run_id,
        "trace_id": f"trace_{collaboration_run_id}",
        "sender": "CongestionAgent",
        "receiver": "FusionAgent",
        "message_type": "analysis",
        "payload": {"rawTranscriptSentinel": "MUST_NOT_STORE_RAW_MESSAGE"},
        "created_at": "2026-06-30T08:06:30Z",
    })


def _save_plan_definition(
    repo: SQLiteWorkflowRepository,
    *,
    plan_id: str,
    event_id: str,
    collaboration_run_id: str = "",
    version: int = 1,
) -> Plan:
    steps = [
        PlanStep(
            stepId="validate_event",
            stepType=NodeType.VALIDATE_EVENT,
            objective="核验事件事实",
        ),
        PlanStep(
            stepId="notify_ops",
            stepType=NodeType.ACTION,
            objective="通知值守人员",
            dependsOn=["validate_event"],
            actionType="notify_wechat",
            approvalRequired=True,
            riskLevel="high",
            evidenceRefs=[{"docId": "doc_policy"}],
        ),
    ]
    plan = Plan(
        planId=plan_id,
        planFingerprint=f"fp_{plan_id}_{version}",
        goal="人民路拥堵处置方案",
        goalType=GoalType.CONGESTION_RESOLUTION,
        definitionStatus=PlanDefinitionStatus.ACTIVE,
        version=version,
        steps=steps,
        eventId=event_id,
        confidence=0.82,
        evidenceRefs=[{"docId": "doc_policy"}],
        metadata={
            "sourceAgent": {
                "sessionId": "sess_case",
                "collaborationRunId": collaboration_run_id,
            },
            "agentRecommendationAudit": {
                "acceptedActions": [{"actionType": "notify_wechat"}],
                "rejectedActions": [{"actionType": "simulation_monitor", "reason": "simulation_only"}],
            },
        },
        createdAt="2026-06-30T08:08:00Z",
        updatedAt="2026-06-30T08:09:00Z",
    )
    definition = plan_to_definition(plan)
    repo.save_definition(definition)
    repo.save_definition_version(WorkflowDefinitionVersion(
        id=f"{plan_id}_v{version}",
        definition_id=plan.planId,
        version=version,
        definition_json=definition.to_dict(),
        changelog="fixture",
        created_at=f"2026-06-30T08:09:0{version}Z",
    ))
    return plan


def _save_workflow_chain(
    isolated,
    *,
    event_id: str,
    run_id: str,
    status: WorkflowRunStatus = WorkflowRunStatus.COMPLETED,
    completed_at: str = "2026-06-30T09:00:00Z",
    plan_id: str = "plan_case",
    session_id: str = "sess_case",
    collaboration_run_id: str = "collab_case",
    bind_location: bool = True,
    save_collaboration: bool = True,
) -> None:
    _seed_event(event_id)
    if bind_location:
        _bind_event(isolated["regionalRepo"], event_id)
    if save_collaboration:
        _save_collaboration_chain(
            isolated["collaborationRepo"],
            event_id=event_id,
            collaboration_run_id=collaboration_run_id,
            session_id=session_id,
        )
    _save_plan_definition(
        isolated["workflowRepo"],
        plan_id=plan_id,
        event_id=event_id,
        collaboration_run_id=collaboration_run_id,
    )
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id=run_id,
        definition_id=plan_id,
        version=1,
        session_id=session_id,
        status=status,
        current_node_id="close",
        state={
            "currentEvent": {"eventId": event_id, "eventType": "congestion"},
            "auditEvents": [{"type": "workflow_completed"}],
            "errors": ["fixture error"] if status == WorkflowRunStatus.FAILED else [],
        },
        started_at="2026-06-30T08:10:00Z",
        updated_at=completed_at,
        completed_at=completed_at,
        triggered_by="test",
    ))
    decision = (
        ApprovalDecision.REJECTED
        if status == WorkflowRunStatus.REJECTED
        else ApprovalDecision.EDITED
    )
    isolated["workflowRepo"].save_approval(WorkflowApproval(
        approval_id=f"appr_{run_id}",
        run_id=run_id,
        node_id="approval_notify",
        proposed_actions=[{"actionType": "notify_wechat", "params": {}}],
        edited_actions=[{"actionType": "notify_dingtalk", "params": {}}]
        if decision == ApprovalDecision.EDITED
        else [],
        decision=decision,
        reviewer="operator_a",
        comment="同意调整通知渠道" if decision == ApprovalDecision.EDITED else "证据不足，驳回",
        created_at="2026-06-30T08:20:00Z",
        decided_at="2026-06-30T08:21:00Z",
    ))
    action_status = ActionStatus.FAILED if status == WorkflowRunStatus.FAILED else ActionStatus.SUCCEEDED
    isolated["workflowRepo"].save_action_record(WorkflowActionRecord(
        action_id=f"act_{run_id}",
        run_id=run_id,
        node_id="notify_ops",
        action_type="notify_wechat",
        params={"token": "SHOULD_REDACT", "channel": "duty"},
        result={"sent": action_status == ActionStatus.SUCCEEDED},
        status=action_status,
        error="provider timeout" if action_status == ActionStatus.FAILED else "",
        created_at="2026-06-30T08:22:00Z",
        completed_at=completed_at,
    ))


def test_completed_case_builds_from_persisted_source_chain(service, isolated):
    _save_workflow_chain(isolated, event_id="EVT_CASE_OK", run_id="wfrun_case_ok")
    _save_plan_definition(
        isolated["workflowRepo"],
        plan_id="plan_case",
        event_id="EVT_CASE_OK",
        collaboration_run_id="collab_case",
        version=2,
    )

    result = service.build_from_workflow_run("wfrun_case_ok")
    case = result.case

    assert result.created is True
    assert case.case_id == build_case_id("wfrun_case_ok")
    assert case.region_id == "REGION_A"
    assert case.road_id == "ROAD_A_MAIN"
    assert case.intersection_id == "INT_A_MAIN"
    assert case.source_plan_id == "plan_case"
    assert case.source_collaboration_run_id == "collab_case"
    assert case.final_status == "completed"
    assert case.workflow_outcome["businessOutcome"]["status"] == "unknown_without_external_evidence"
    assert case.provenance["rawTranscriptStored"] is False
    encoded = str(case.to_dict())
    assert "MUST_NOT_STORE_RAW_MESSAGE" not in encoded
    assert "RAW_EVENT_SENTINEL" not in encoded
    assert "FULL_RESULT_SENTINEL" not in encoded
    assert "SHOULD_REDACT" not in encoded
    assert case.agent_facts["acceptedActions"][0]["actionType"] == "notify_wechat"
    assert case.agent_facts["rejectedActions"][0]["reason"] == "simulation_only"
    assert case.plan_facts["planId"] == "plan_case"
    assert case.plan_facts["version"] == 1
    assert case.plan_facts["latestVersion"] == 2
    assert case.plan_facts["replanCount"] == 1
    assert case.human_decisions[0]["manualAdjustment"] is True


def test_failed_and_rejected_terminal_workflows_are_supported(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_CASE_FAIL",
        run_id="wfrun_case_fail",
        status=WorkflowRunStatus.FAILED,
        completed_at="2026-06-30T10:00:00Z",
        plan_id="plan_fail",
        collaboration_run_id="collab_fail",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_CASE_REJECT",
        run_id="wfrun_case_reject",
        status=WorkflowRunStatus.REJECTED,
        completed_at="2026-06-30T11:00:00Z",
        plan_id="plan_reject",
        collaboration_run_id="collab_reject",
    )

    failed = service.build_from_workflow_run("wfrun_case_fail").case
    rejected = service.build_from_workflow_run("wfrun_case_reject").case

    assert failed.final_status == "failed"
    assert any(item["type"] == "action_failed" for item in failed.lessons)
    assert any(item["type"] == "workflow_failed" for item in failed.lessons)
    assert rejected.final_status == "rejected"
    assert rejected.human_decisions[0]["decision"] == "rejected"
    assert any(item["type"] == "human_approval_rejected" for item in rejected.lessons)
    query = service.query_cases(region_id="REGION_A", event_type="congestion", for_agent=True, limit=10)
    statuses = {case.final_status for case in query["cases"]}
    assert {"failed", "rejected"}.issubset(statuses)


def test_case_build_requires_terminal_workflow_and_valid_event_relation(service, isolated):
    _seed_event("EVT_NOT_TERMINAL")
    _bind_event(isolated["regionalRepo"], "EVT_NOT_TERMINAL")
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id="wfrun_running",
        definition_id="def_plain",
        status=WorkflowRunStatus.RUNNING,
        state={"currentEvent": {"eventId": "EVT_NOT_TERMINAL"}},
    ))
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id="wfrun_no_event",
        definition_id="def_plain",
        status=WorkflowRunStatus.COMPLETED,
        state={},
        completed_at="2026-06-30T09:00:00Z",
    ))

    with pytest.raises(CaseMemoryError) as not_terminal:
        service.build_from_workflow_run("wfrun_running")
    with pytest.raises(CaseMemoryError) as no_event:
        service.build_from_workflow_run("wfrun_no_event")

    assert not_terminal.value.code == "CASE_NOT_BUILDABLE_WORKFLOW_NOT_TERMINAL"
    assert no_event.value.code == "CASE_NOT_BUILDABLE_EVENT_RELATION_MISSING"


def test_case_build_requires_canonical_region_not_road_name(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_NO_REGION",
        run_id="wfrun_no_region",
        bind_location=False,
        plan_id="plan_no_region",
        collaboration_run_id="collab_no_region",
    )

    with pytest.raises(CaseMemoryError) as exc:
        service.build_from_workflow_run("wfrun_no_region")

    assert exc.value.code == "CASE_NOT_BUILDABLE_CANONICAL_REGION_MISSING"
    assert isolated["caseRepo"].get_case_by_source_workflow_run_id("wfrun_no_region") is None


def test_simulation_workflow_is_not_buildable(service, isolated):
    _seed_event("simevt_case")
    _bind_event(isolated["regionalRepo"], "simevt_case")
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id="wfrun_simulation",
        definition_id="def_plain",
        status=WorkflowRunStatus.COMPLETED,
        state={
            "currentEvent": {
                "eventId": "simevt_case",
                "eventType": "congestion",
                "simulationRunId": "simrun_001",
            },
            "simulationRefs": ["simrun_001"],
        },
        completed_at="2026-06-30T09:00:00Z",
    ))

    with pytest.raises(CaseMemoryError) as exc:
        service.build_from_workflow_run("wfrun_simulation")

    assert exc.value.code == "CASE_NOT_BUILDABLE_SIMULATION_SOURCE"
    assert isolated["caseRepo"].get_case_by_source_workflow_run_id("wfrun_simulation") is None


def test_schema_bootstrap_does_not_auto_create_case(isolated):
    _save_workflow_chain(isolated, event_id="EVT_BOOTSTRAP", run_id="wfrun_bootstrap")

    init_case_memory_tables()

    assert isolated["caseRepo"].get_case_by_source_workflow_run_id("wfrun_bootstrap") is None


def test_idempotent_second_build_and_explicit_rebuild_preserve_case_id(service, isolated):
    _save_workflow_chain(isolated, event_id="EVT_IDEMPOTENT", run_id="wfrun_idempotent")

    first = service.build_from_workflow_run("wfrun_idempotent")
    second = service.build_from_workflow_run("wfrun_idempotent")
    rebuild = service.build_from_workflow_run("wfrun_idempotent", rebuild=True)

    assert first.created is True
    assert second.created is False
    assert second.rebuilt is False
    assert rebuild.created is False
    assert rebuild.rebuilt is True
    assert first.case.case_id == second.case.case_id == rebuild.case.case_id
    cases = isolated["caseRepo"].list_cases_for_source_event("EVT_IDEMPOTENT")
    assert len(cases) == 1


def test_rebuild_uses_current_canonical_binding_and_preserves_case_id(service, isolated):
    _save_workflow_chain(isolated, event_id="EVT_RERESOLVE", run_id="wfrun_reresolve")
    first = service.build_from_workflow_run("wfrun_reresolve").case

    isolated["regionalRepo"].save_resolved_event_location_binding(
        {
            "status": "resolved",
            "eventId": "EVT_RERESOLVE",
            "regionId": "REGION_A",
            "roadId": "ROAD_A_SIDE",
            "intersectionId": None,
            "resolutionMethod": "manual_correction",
            "matchedAlias": "解放路",
        },
        re_resolve=True,
    )
    rebuilt = service.build_from_workflow_run("wfrun_reresolve", rebuild=True).case

    assert rebuilt.case_id == first.case_id
    assert rebuilt.road_id == "ROAD_A_SIDE"
    assert rebuilt.intersection_id is None
    assert rebuilt.provenance["canonicalLocation"]["roadId"] == "ROAD_A_SIDE"


def test_first_build_race_returns_existing_case_without_duplicate(service, isolated):
    _save_workflow_chain(isolated, event_id="EVT_RACE", run_id="wfrun_race")
    built_case = service.builder.build_from_workflow_run("wfrun_race")

    class StubBuilder:
        def build_from_workflow_run(self, run_id):
            assert run_id == "wfrun_race"
            return built_case

    class RaceRepo:
        def __init__(self):
            self.reads = 0

        def get_case_by_source_workflow_run_id(self, run_id):
            self.reads += 1
            return None if self.reads == 1 else built_case

        def insert_case(self, case):
            raise sqlite3.IntegrityError("source_workflow_run_id")

    race_repo = RaceRepo()
    race_service = TrafficCaseMemoryService(repository=race_repo, builder=StubBuilder())

    result = race_service.build_from_workflow_run("wfrun_race")

    assert result.case.case_id == built_case.case_id
    assert result.created is False
    assert result.rebuilt is False


def test_same_event_multiple_analysis_plan_workflow_chains_do_not_cross(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_MULTI",
        run_id="wfrun_multi_a",
        completed_at="2026-06-30T09:00:00Z",
        plan_id="plan_multi_a",
        collaboration_run_id="collab_multi_a",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_MULTI",
        run_id="wfrun_multi_b",
        completed_at="2026-06-30T10:00:00Z",
        plan_id="plan_multi_b",
        collaboration_run_id="collab_multi_b",
    )

    case_a = service.build_from_workflow_run("wfrun_multi_a").case
    case_b = service.build_from_workflow_run("wfrun_multi_b").case

    assert case_a.case_id != case_b.case_id
    assert case_a.event_id == case_b.event_id == "EVT_MULTI"
    assert case_a.source_plan_id == "plan_multi_a"
    assert case_a.source_collaboration_run_id == "collab_multi_a"
    assert case_b.source_plan_id == "plan_multi_b"
    assert case_b.source_collaboration_run_id == "collab_multi_b"
    encoded_a = str(case_a.to_dict())
    assert "plan_multi_b" not in encoded_a
    assert "collab_multi_b" not in encoded_a
    assert "appr_wfrun_multi_b" not in encoded_a
    assert "act_wfrun_multi_b" not in encoded_a


def test_query_blocks_cross_region_and_uses_canonical_location(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_REGION_A",
        run_id="wfrun_region_a",
        plan_id="plan_region_a",
        collaboration_run_id="collab_region_a",
    )
    isolated["regionalRepo"].import_context_pack(_context_pack_b())
    _seed_event("EVT_REGION_B", road_name="人民路", analyzed_at="2026-06-29T08:00:00Z")
    _bind_event(
        isolated["regionalRepo"],
        "EVT_REGION_B",
        region_id="REGION_B",
        road_id="ROAD_B_MAIN",
        intersection_id="INT_B_MAIN",
    )
    _save_collaboration_chain(
        isolated["collaborationRepo"],
        event_id="EVT_REGION_B",
        collaboration_run_id="collab_region_b",
        session_id="sess_b",
    )
    _save_plan_definition(
        isolated["workflowRepo"],
        plan_id="plan_region_b",
        event_id="EVT_REGION_B",
        collaboration_run_id="collab_region_b",
    )
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id="wfrun_region_b",
        definition_id="plan_region_b",
        session_id="sess_b",
        status=WorkflowRunStatus.COMPLETED,
        state={"currentEvent": {"eventId": "EVT_REGION_B", "eventType": "congestion"}},
        completed_at="2026-06-29T10:00:00Z",
    ))
    service.build_from_workflow_run("wfrun_region_a")
    service.build_from_workflow_run("wfrun_region_b")

    region_a = service.query_cases(region_id="REGION_A", event_type="congestion", for_agent=True)
    region_b = service.query_cases(region_id="REGION_B", event_type="congestion", for_agent=True)
    road_filtered = service.query_cases(
        region_id="REGION_A",
        event_type="congestion",
        road_id="ROAD_A_MAIN",
        for_agent=True,
    )

    assert [case.event_id for case in region_a["cases"]] == ["EVT_REGION_A"]
    assert [case.event_id for case in region_b["cases"]] == ["EVT_REGION_B"]
    assert [case.event_id for case in road_filtered["cases"]] == ["EVT_REGION_A"]


def test_case_context_excludes_future_cases_for_holdout(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_OLD_1",
        run_id="wfrun_old_1",
        completed_at="2026-06-10T10:00:00Z",
        plan_id="plan_old_1",
        collaboration_run_id="collab_old_1",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_OLD_2",
        run_id="wfrun_old_2",
        status=WorkflowRunStatus.FAILED,
        completed_at="2026-06-25T10:00:00Z",
        plan_id="plan_old_2",
        collaboration_run_id="collab_old_2",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_EQUAL",
        run_id="wfrun_equal",
        completed_at="2026-06-30T08:00:00Z",
        plan_id="plan_equal",
        collaboration_run_id="collab_equal",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_FUTURE",
        run_id="wfrun_future",
        completed_at="2026-07-02T10:00:00Z",
        plan_id="plan_future",
        collaboration_run_id="collab_future",
    )
    isolated["regionalRepo"].import_context_pack(_context_pack_b())
    _seed_event("EVT_REGION_B_HOLDOUT", road_name="人民路", analyzed_at="2026-06-15T08:00:00Z")
    _bind_event(
        isolated["regionalRepo"],
        "EVT_REGION_B_HOLDOUT",
        region_id="REGION_B",
        road_id="ROAD_B_MAIN",
        intersection_id="INT_B_MAIN",
    )
    _save_collaboration_chain(
        isolated["collaborationRepo"],
        event_id="EVT_REGION_B_HOLDOUT",
        collaboration_run_id="collab_region_b_holdout",
        session_id="sess_b_holdout",
    )
    _save_plan_definition(
        isolated["workflowRepo"],
        plan_id="plan_region_b_holdout",
        event_id="EVT_REGION_B_HOLDOUT",
        collaboration_run_id="collab_region_b_holdout",
    )
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id="wfrun_region_b_holdout",
        definition_id="plan_region_b_holdout",
        session_id="sess_b_holdout",
        status=WorkflowRunStatus.COMPLETED,
        state={"currentEvent": {"eventId": "EVT_REGION_B_HOLDOUT", "eventType": "congestion"}},
        completed_at="2026-06-15T10:00:00Z",
    ))
    _seed_event("EVT_TARGET", analyzed_at="2026-06-30T08:00:00Z")
    _bind_event(isolated["regionalRepo"], "EVT_TARGET")
    service.build_from_workflow_run("wfrun_old_1")
    service.build_from_workflow_run("wfrun_old_2")
    service.build_from_workflow_run("wfrun_equal")
    service.build_from_workflow_run("wfrun_future")
    service.build_from_workflow_run("wfrun_region_b_holdout")

    context = service.get_case_context_for_event("EVT_TARGET", limit=5)

    event_ids = [case["eventId"] for case in context["cases"]]
    assert event_ids == ["EVT_OLD_2", "EVT_OLD_1"]
    assert context["retrievalPolicy"]["crossRegionBlocked"] is True
    assert context["retrievalPolicy"]["futureCaseLeakageBlocked"] is True
    assert context["retrievalPolicy"]["roadNameUsedAsIdentity"] is False


def test_case_asof_uses_datetime_order_not_string_order(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_SPACE_OLD",
        run_id="wfrun_space_old",
        completed_at="2026-06-30 07:00:00",
        plan_id="plan_space_old",
        collaboration_run_id="collab_space_old",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_SPACE_LATE",
        run_id="wfrun_space_late",
        completed_at="2026-06-30 09:00:00",
        plan_id="plan_space_late",
        collaboration_run_id="collab_space_late",
    )
    _seed_event("EVT_SPACE_TARGET", analyzed_at="2026-06-30T08:00:00Z")
    _bind_event(isolated["regionalRepo"], "EVT_SPACE_TARGET")
    service.build_from_workflow_run("wfrun_space_old")
    service.build_from_workflow_run("wfrun_space_late")

    context = service.get_case_context_for_event("EVT_SPACE_TARGET", limit=5)

    assert [case["eventId"] for case in context["cases"]] == ["EVT_SPACE_OLD"]


def test_case_context_ordering_uses_canonical_specificity_before_recency(service, isolated):
    _save_workflow_chain(
        isolated,
        event_id="EVT_SPEC_INTERSECTION",
        run_id="wfrun_spec_intersection",
        completed_at="2026-06-10T10:00:00Z",
        plan_id="plan_spec_intersection",
        collaboration_run_id="collab_spec_intersection",
        bind_location=False,
    )
    _bind_event(
        isolated["regionalRepo"],
        "EVT_SPEC_INTERSECTION",
        road_id="ROAD_A_MAIN",
        intersection_id="INT_A_MAIN",
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_SPEC_ROAD",
        run_id="wfrun_spec_road",
        completed_at="2026-06-20T10:00:00Z",
        plan_id="plan_spec_road",
        collaboration_run_id="collab_spec_road",
        bind_location=False,
    )
    _bind_event(
        isolated["regionalRepo"],
        "EVT_SPEC_ROAD",
        road_id="ROAD_A_MAIN",
        intersection_id=None,
    )
    _save_workflow_chain(
        isolated,
        event_id="EVT_SPEC_REGION",
        run_id="wfrun_spec_region",
        completed_at="2026-06-25T10:00:00Z",
        plan_id="plan_spec_region",
        collaboration_run_id="collab_spec_region",
        bind_location=False,
    )
    _bind_event(
        isolated["regionalRepo"],
        "EVT_SPEC_REGION",
        road_id="ROAD_A_SIDE",
        intersection_id=None,
    )
    _seed_event("EVT_SPEC_TARGET", analyzed_at="2026-06-30T08:00:00Z")
    _bind_event(
        isolated["regionalRepo"],
        "EVT_SPEC_TARGET",
        road_id="ROAD_A_MAIN",
        intersection_id="INT_A_MAIN",
    )
    service.build_from_workflow_run("wfrun_spec_intersection")
    service.build_from_workflow_run("wfrun_spec_road")
    service.build_from_workflow_run("wfrun_spec_region")

    context = service.get_case_context_for_event("EVT_SPEC_TARGET", limit=3)

    assert context["total"] == 3
    assert [case["eventId"] for case in context["cases"]] == [
        "EVT_SPEC_INTERSECTION",
        "EVT_SPEC_ROAD",
        "EVT_SPEC_REGION",
    ]


def test_api_build_get_query_and_context_contract(api_client, isolated):
    _save_workflow_chain(isolated, event_id="EVT_API", run_id="wfrun_api")

    build_resp = api_client.post("/case-memory/from-workflow/wfrun_api")
    second_resp = api_client.post("/case-memory/from-workflow/wfrun_api")
    query_resp = api_client.get("/case-memory", params={
        "regionId": "REGION_A",
        "eventType": "congestion",
        "forAgent": True,
    })
    context_resp = api_client.get("/case-memory/events/EVT_API")
    case_id = build_resp.json()["case"]["caseId"]
    get_resp = api_client.get(f"/case-memory/{case_id}")

    assert build_resp.status_code == 200
    assert build_resp.json()["created"] is True
    assert second_resp.json()["newCases"] == 0
    assert query_resp.status_code == 200
    assert query_resp.json()["total"] == 1
    assert context_resp.status_code == 200
    assert context_resp.json()["eventId"] == "EVT_API"
    assert get_resp.json()["caseId"] == case_id


def test_api_rejects_non_terminal_without_creating_case(api_client, isolated):
    _seed_event("EVT_API_RUNNING")
    _bind_event(isolated["regionalRepo"], "EVT_API_RUNNING")
    isolated["workflowRepo"].save_run(WorkflowRun(
        run_id="wfrun_api_running",
        definition_id="def_plain",
        status=WorkflowRunStatus.RUNNING,
        state={"currentEvent": {"eventId": "EVT_API_RUNNING"}},
    ))

    resp = api_client.post("/case-memory/from-workflow/wfrun_api_running")

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CASE_NOT_BUILDABLE_WORKFLOW_NOT_TERMINAL"
    assert isolated["caseRepo"].get_case_by_source_workflow_run_id("wfrun_api_running") is None
