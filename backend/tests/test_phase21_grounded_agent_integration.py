"""Phase21 Wave F grounded real-event Agent integration tests.

The tests exercise the existing routed Agent stream and AgentPlanningAdapter
with isolated persisted data. They do not create production DB state.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.agent.collaboration.db_repository as collab_db
import backend.chat.chat_db as chat_db
import backend.config as cfg
import backend.tools.db_tools as db_tools
from backend.agent.collaboration.db_repository import (
    SQLiteCollaborationRepository,
    init_collaboration_tables,
)
from backend.agent.collaboration.budget import ExecutionBudget
from backend.agent.collaboration.executor import execute_single_agent
from backend.agent.collaboration.state import CollaborationRunState
from backend.agent.collaboration.task_graph import AgentTaskNode
from backend.case_memory.models import CaseMemoryQuality, TrafficCaseMemory
from backend.case_memory.repository import SQLiteCaseMemoryRepository, init_case_memory_tables
from backend.regional.repository import SQLiteRegionalRepository
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    production_db = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
    event_db = str(tmp_path / "phase21_wave_f_agent.db")
    rag_db = str(tmp_path / "phase21_wave_f_agent_rag.db")
    chroma_path = str(tmp_path / "phase21_wave_f_agent_chroma")
    fts_path = str(tmp_path / "phase21_wave_f_agent_fts.db")
    assert event_db != production_db

    monkeypatch.setattr(cfg, "DB_PATH", event_db)
    monkeypatch.setattr(db_tools, "DB_PATH", event_db)
    monkeypatch.setattr(chat_db, "DB_PATH", event_db)
    monkeypatch.setattr(collab_db, "DB_PATH", event_db)
    chat_db.reset_initialized()
    db_tools.init_db()
    chat_db.init_chat_tables()
    init_workflow_tables()
    init_collaboration_tables()
    init_case_memory_tables()

    import backend.rag.v2.config as v2cfg
    import backend.rag.v2.dense_index as dense_idx
    import backend.rag.v2.document_repository as doc_repo
    import backend.rag.v2.sparse_index as sparse_idx
    from backend.rag.v2.providers import FakeEmbeddingProvider, FakeRerankerProvider

    monkeypatch.setattr(v2cfg, "RAG_V2_DB_PATH", rag_db)
    monkeypatch.setattr(doc_repo, "RAG_V2_DB_PATH", rag_db)
    monkeypatch.setattr(v2cfg, "RAG_V2_FTS_PATH", fts_path)
    monkeypatch.setattr(sparse_idx, "RAG_V2_FTS_PATH", fts_path)
    dense_idx._VECTOR_DB_PATH = chroma_path
    monkeypatch.setattr(dense_idx, "_get_vector_db_path", lambda: chroma_path)

    fake_provider = FakeEmbeddingProvider(dimension=384)
    fake_reranker = FakeRerankerProvider()
    monkeypatch.setattr("backend.rag.v2.providers.get_embedding_provider", lambda: fake_provider)
    monkeypatch.setattr("backend.rag.v2.providers.get_reranker_provider", lambda: fake_reranker)
    monkeypatch.setattr("backend.knowledge.service.get_embedding_provider", lambda: fake_provider)
    sparse_idx.init_fts()
    doc_repo.init_db()

    regional_repo = SQLiteRegionalRepository(db_path=event_db)
    regional_repo.import_context_pack(_region_a_pack())
    regional_repo.import_context_pack(_region_b_pack())
    workflow_repo = SQLiteWorkflowRepository()
    monkeypatch.setattr("backend.planning.api._repo", workflow_repo)
    monkeypatch.setattr("backend.workflow.api._repo", workflow_repo)
    return {
        "db": event_db,
        "productionDb": production_db,
        "regionalRepo": regional_repo,
        "caseRepo": SQLiteCaseMemoryRepository(),
        "collabRepo": SQLiteCollaborationRepository(),
    }


@pytest.fixture()
def app_client(isolated, monkeypatch):
    import backend.agent.collaboration.orchestrator as orchestrator_mod
    import backend.app as app_mod

    monkeypatch.setattr(app_mod, "LLM_ENABLED", False)
    monkeypatch.setattr(orchestrator_mod, "LLM_ENABLED", False)

    async def memory_stub(*args, **kwargs):
        return {
            "runId": args[1],
            "sessionId": args[0],
            "candidateCount": 0,
            "createdCount": 0,
            "deduplicatedCount": 0,
            "supersededCount": 0,
            "rejectedCount": 0,
            "confirmedCount": 0,
            "latencyMs": 0,
            "traceId": "memory_stub",
            "writeResults": [],
        }

    class RecallStub:
        def recall_and_inject(self, **kwargs):
            return {
                "eventThreadId": "thread_grounded_fixture",
                "intent": "none",
                "candidateCount": 0,
                "selectedCount": 0,
                "rejectedCount": 0,
                "latencyMs": 0,
                "tokenEstimate": 0,
                "routingContext": {},
                "agentInjectionMap": {},
            }

    monkeypatch.setattr(app_mod, "_run_memory_extraction", memory_stub)
    monkeypatch.setattr("backend.memory.coordinator.MemoryCoordinator", RecallStub)
    return TestClient(app_mod.app)


def _region_a_pack() -> Dict[str, Any]:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_grounded_agent_integration.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_A",
            "name": "测试区域A",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {"roadId": "ROAD_A_PEOPLE", "regionId": "TEST_REGION_A", "name": "人民路"},
            {"roadId": "ROAD_A_LIBERATION", "regionId": "TEST_REGION_A", "name": "解放路"},
            {"roadId": "ROAD_A_YOUTH", "regionId": "TEST_REGION_A", "name": "青年路"},
        ],
        "intersections": [
            {
                "intersectionId": "INT_A_PEOPLE_LIBERATION",
                "regionId": "TEST_REGION_A",
                "name": "人民路-解放路路口",
            },
            {
                "intersectionId": "INT_A_YOUTH",
                "regionId": "TEST_REGION_A",
                "name": "青年路路口",
            }
        ],
        "roadRelations": [
            {
                "relationId": "REL_A_PEOPLE_CONNECT",
                "regionId": "TEST_REGION_A",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_A_PEOPLE",
                "toEntityType": "intersection",
                "toEntityId": "INT_A_PEOPLE_LIBERATION",
                "relationType": "connects",
            },
            {
                "relationId": "REL_A_LIBERATION_CONNECT",
                "regionId": "TEST_REGION_A",
                "fromEntityType": "intersection",
                "fromEntityId": "INT_A_PEOPLE_LIBERATION",
                "toEntityType": "road",
                "toEntityId": "ROAD_A_LIBERATION",
                "relationType": "connects",
            },
            {
                "relationId": "REL_A_YOUTH_CONNECT",
                "regionId": "TEST_REGION_A",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_A_YOUTH",
                "toEntityType": "intersection",
                "toEntityId": "INT_A_YOUTH",
                "relationType": "connects",
            },
        ],
        "pois": [],
    }


def _region_b_pack() -> Dict[str, Any]:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_grounded_agent_integration.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_B",
            "name": "测试区域B",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [{"roadId": "ROAD_B_OTHER", "regionId": "TEST_REGION_B", "name": "外环路"}],
        "intersections": [
            {
                "intersectionId": "INT_B_OTHER",
                "regionId": "TEST_REGION_B",
                "name": "外环路-支路路口",
            }
        ],
        "roadRelations": [],
        "pois": [],
    }


def _seed_event(
    event_id: str,
    *,
    road_name: str = "人民路-解放路路口",
    event_type: str = "accident",
    analyzed_at: str = "2026-06-30T08:00:00Z",
    status: str = "待派单",
) -> None:
    event_type_cn = "事故" if event_type == "accident" else "拥堵"
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": event_type,
            "eventTypeCn": event_type_cn,
            "roadName": road_name,
            "direction": "东向西",
            "avgSpeed": 8,
            "queueLength": 220,
            "duration": 4200,
            "weather": "rain",
            "timePeriod": "morning_peak",
            "isMainRoad": True,
            "nearbySchool": False,
            "nearbyHospital": False,
            "debugOnly": "RAW_EVENT_SENTINEL",
        },
        "riskScore": 96,
        "riskLevel": "重大风险",
        "status": status,
        "report": "synthetic fixture report",
        "analyzedAt": analyzed_at,
        "debugPayload": "FULL_RESULT_SENTINEL",
    })


def _bind_event(
    repo: SQLiteRegionalRepository,
    event_id: str,
    *,
    region_id: str = "TEST_REGION_A",
    road_id: str = "ROAD_A_PEOPLE",
    intersection_id: str = "INT_A_PEOPLE_LIBERATION",
    re_resolve: bool = False,
) -> None:
    repo.save_resolved_event_location_binding({
        "eventId": event_id,
        "status": "resolved",
        "resolutionMethod": "TEST_BINDING",
        "regionId": region_id,
        "roadId": road_id,
        "intersectionId": intersection_id,
        "matchedAlias": "人民路",
    }, re_resolve=re_resolve)


def _create_doc(name: str, content: str, metadata: Dict[str, Any]) -> dict:
    from backend.knowledge.service import create_document

    return create_document(
        name=name,
        doc_type="rule",
        content=f"## {name}\n\n{content}",
        metadata={
            "sourceId": f"test:{name}",
            "authorityLevel": "official",
            **metadata,
        },
    )


def _insert_case(
    case_repo: SQLiteCaseMemoryRepository,
    case_id: str,
    *,
    region_id: str = "TEST_REGION_A",
    road_id: str = "ROAD_A_PEOPLE",
    intersection_id: str = "INT_A_PEOPLE_LIBERATION",
    completed_at: str = "2026-06-20T08:00:00Z",
) -> None:
    case_repo.insert_case(TrafficCaseMemory(
        case_id=case_id,
        region_id=region_id,
        event_id=f"E_SRC_{case_id}",
        event_type="accident",
        road_id=road_id,
        intersection_id=intersection_id,
        source_workflow_run_id=f"wfrun_{case_id}",
        source_collaboration_run_id=f"collab_{case_id}",
        source_plan_id=f"plan_{case_id}",
        final_status="completed",
        quality_status=CaseMemoryQuality.VALIDATED,
        generated_summary=f"{case_id} 复盘摘要",
        lessons=[{"type": "dispatch", "severity": "high", "summary": f"{case_id} lessons"}],
        started_at="2026-06-20T07:30:00Z",
        completed_at=completed_at,
        source_type="synthetic_fixture",
    ))


def _prepare_grounded_event(isolated, event_id: str = "E_AGENT_GROUNDED") -> None:
    repo = isolated["regionalRepo"]
    _seed_event(event_id, analyzed_at="2026-06-30T08:00:00Z")
    _seed_event("E_AGENT_HISTORY", analyzed_at="2026-06-20T08:00:00Z")
    _seed_event("E_AGENT_FUTURE", analyzed_at="2026-07-01T08:00:00Z")
    _bind_event(repo, event_id)
    _bind_event(repo, "E_AGENT_HISTORY")
    _bind_event(repo, "E_AGENT_FUTURE")
    _create_doc(
        "人民路事故协同规则",
        "重大风险事故应联动指挥中心并保持救援通道。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "intersectionId": "INT_A_PEOPLE_LIBERATION",
            "eventType": "accident",
            "effectiveFrom": "2026-01-01T00:00:00Z",
        },
    )
    _create_doc(
        "未来事故规则",
        "未来才生效的规则不得被当前事件使用。",
        {
            "regionId": "TEST_REGION_A",
            "eventType": "accident",
            "effectiveFrom": "2026-07-01T00:00:00Z",
        },
    )
    _create_doc(
        "外环路事故规则",
        "错误区域规则不得进入人民路事件研判。",
        {
            "regionId": "TEST_REGION_B",
            "roadId": "ROAD_B_OTHER",
            "intersectionId": "INT_B_OTHER",
            "eventType": "accident",
            "effectiveFrom": "2026-01-01T00:00:00Z",
        },
    )
    _insert_case(isolated["caseRepo"], "case_agent_past", completed_at="2026-06-25T08:00:00Z")
    _insert_case(isolated["caseRepo"], "case_agent_future", completed_at="2026-07-01T08:00:00Z")
    _insert_case(
        isolated["caseRepo"],
        "case_agent_region_b",
        region_id="TEST_REGION_B",
        road_id="ROAD_B_OTHER",
        intersection_id="INT_B_OTHER",
        completed_at="2026-06-25T08:00:00Z",
    )


def _json_field(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _run_from_response(text: str, collab_repo: SQLiteCollaborationRepository, event_id: str) -> Dict[str, Any]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == "event: run_created" and index + 1 < len(lines):
            payload = lines[index + 1]
            if not payload.startswith("data: "):
                continue
            run_id = json.loads(payload.removeprefix("data: "))["runId"]
            run = collab_repo.get_run(run_id)
            if run:
                return run
    rows = collab_repo.list_runs_by_event_id(event_id, limit=1)
    assert rows
    return rows[0]


def _run_grounded_stream(
    app_client,
    isolated,
    monkeypatch,
    event_id: str = "E_AGENT_GROUNDED",
    agent_impl=None,
):
    captured: Dict[str, Dict[str, Any]] = {}

    async def fake_agent_call(agent_name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        captured[agent_name] = ctx
        if agent_impl is not None:
            return await agent_impl(agent_name, ctx)
        return {
            "agentName": agent_name,
            "findings": [f"{agent_name} 基于输入完成研判"],
            "confidence": 0.86,
            "suggestion": f"{agent_name} 建议联动处置",
            "urgency": "high",
            "proposed_actions": [
                {"actionType": "notify_dingtalk", "params": {"message": "重大风险事故"}},
                {"actionType": "grounding_magic", "params": {}},
                {"actionType": "simulation_monitor", "params": {}},
            ],
        }

    monkeypatch.setattr("backend.agent.collaboration.executor._call_agent_function", fake_agent_call)
    response = app_client.post("/agent/routed_analyze/stream", json={
        "eventId": event_id,
        "content": "请基于真实事件、区域、历史、知识和案例做协同研判",
        "contextPolicy": "fresh_event",
    })
    assert response.status_code == 200
    assert "event: grounding_ready" in response.text
    assert "event: run_completed" in response.text
    run = _run_from_response(response.text, isolated["collabRepo"], event_id)
    return response.text, run, captured


def test_routed_agent_stream_receives_consumes_and_persists_grounded_context(
    isolated,
    app_client,
    monkeypatch,
):
    _prepare_grounded_event(isolated)

    _, run, captured = _run_grounded_stream(app_client, isolated, monkeypatch)
    tasks = isolated["collabRepo"].list_tasks(run["run_id"])
    task_inputs = {
        task["agent_name"]: _json_field(task.get("input_snapshot"), {})
        for task in tasks
    }
    task_outputs = {
        task["agent_name"]: _json_field(task.get("output_snapshot"), {})
        for task in tasks
    }
    grounding = _json_field(run.get("grounding_context"), {})
    final = _json_field(run.get("final_decision"), {})
    serialized = json.dumps({"run": run, "tasks": tasks}, ensure_ascii=False, sort_keys=True)

    assert run["status"] == "completed"
    assert _json_field(run["normalized_event"], {})["eventId"] == "E_AGENT_GROUNDED"
    assert grounding["groundingStatus"] == "FULL"
    assert grounding["regionalContext"]["location"]["regionId"] == "TEST_REGION_A"
    assert grounding["historicalContext"]["eventCount"] == 1
    assert grounding["caseMemoryContext"]["cases"][0]["caseId"] == "case_agent_past"
    assert final["groundingAudit"]["groundingStatus"] == "FULL"
    assert final["groundingAudit"]["regionId"] == "TEST_REGION_A"

    assert "AccidentAgent" in captured
    assert "CongestionAgent" in captured
    for agent_name in ("AccidentAgent", "CongestionAgent", "DispatchAgent", "FusionAgent"):
        assert task_inputs[agent_name]["groundedContext"]["currentEvent"]["eventId"] == "E_AGENT_GROUNDED"
        assert task_inputs[agent_name]["groundingFacts"]
        assert task_inputs[agent_name]["groundingEvidenceRefs"]

    for agent_name in ("AccidentAgent", "CongestionAgent"):
        output = task_outputs[agent_name]
        assert any("GroundedEventContext" in item for item in output["findings"])
        assert any(ref.get("type") == "knowledge_evidence" for ref in output["evidence_refs"])
        assert any(ref.get("type") == "case_memory" for ref in output["evidence_refs"])
        assert output["assumptions"]

    assert "E_AGENT_FUTURE" not in serialized
    assert "case_agent_future" not in serialized
    assert "case_agent_region_b" not in serialized
    assert "未来事故规则" not in serialized
    assert "外环路事故规则" not in serialized
    assert "RAW_EVENT_SENTINEL" not in serialized
    assert "FULL_RESULT_SENTINEL" not in serialized
    assert "rawEvent" not in serialized
    assert "fullResult" not in serialized


def test_agent_plan_adapter_carries_compact_grounding_audit_and_rejects_unsupported_actions(
    isolated,
    app_client,
    monkeypatch,
):
    _prepare_grounded_event(isolated)
    _, run, _ = _run_grounded_stream(app_client, isolated, monkeypatch)

    response = app_client.post("/planning/plans/from-agent", json={
        "eventId": "E_AGENT_GROUNDED",
        "sessionId": run["session_id"],
        "collaborationRunId": run["run_id"],
    })
    assert response.status_code == 200
    body = response.json()
    audit = body["plan"]["metadata"]["agentGroundingAudit"]
    accepted = body["agentRecommendationAudit"]["accepted"]
    rejected = body["agentRecommendationAudit"]["rejected"]
    serialized_plan = json.dumps(body["plan"], ensure_ascii=False, sort_keys=True)

    assert body["sourceAgent"]["collaborationRunId"] == run["run_id"]
    assert body["sourceAgent"]["groundingStatus"] == "FULL"
    assert audit["groundingStatus"] == "FULL"
    assert audit["regionId"] == "TEST_REGION_A"
    assert any(ref["type"] == "knowledge_evidence" for ref in audit["refs"])
    assert any(ref["type"] == "case_memory" for ref in audit["refs"])
    assert any(item["actionType"] == "notify_dingtalk" for item in accepted)
    assert any(item.get("actionType") == "grounding_magic" for item in rejected)
    assert any(item.get("actionType") == "simulation_monitor" for item in rejected)
    plan_action_types = [
        step.get("actionType")
        for step in body["plan"]["steps"]
        if step.get("stepType") == "action"
    ]
    assert "notify_dingtalk" in plan_action_types
    assert "grounding_magic" not in plan_action_types
    assert "simulation_monitor" not in plan_action_types
    assert "RAW_EVENT_SENTINEL" not in serialized_plan
    assert "FULL_RESULT_SENTINEL" not in serialized_plan
    assert "rawEvent" not in serialized_plan
    assert "fullResult" not in serialized_plan


def test_persisted_grounding_snapshot_is_stable_across_later_runs(
    isolated,
    app_client,
    monkeypatch,
):
    _prepare_grounded_event(isolated)
    _, first_run, _ = _run_grounded_stream(app_client, isolated, monkeypatch)
    first_snapshot = _json_field(first_run["grounding_context"], {})

    _create_doc(
        "新增人民路事故规则",
        "第二次运行前新增的知识只应进入后续快照。",
            {
                "regionId": "TEST_REGION_A",
                "roadId": "ROAD_A_PEOPLE",
                "intersectionId": "INT_A_PEOPLE_LIBERATION",
                "eventType": "accident",
                "effectiveFrom": "2026-01-01T00:00:00Z",
            },
    )
    _insert_case(isolated["caseRepo"], "case_agent_new", completed_at="2026-06-26T08:00:00Z")
    _, second_run, _ = _run_grounded_stream(
        app_client,
        isolated,
        monkeypatch,
        event_id="E_AGENT_GROUNDED",
    )

    first_reloaded = isolated["collabRepo"].get_run(first_run["run_id"])
    assert _json_field(first_reloaded["grounding_context"], {}) == first_snapshot
    second_snapshot = _json_field(second_run["grounding_context"], {})
    first_text = json.dumps(first_snapshot, ensure_ascii=False, sort_keys=True)
    second_text = json.dumps(second_snapshot, ensure_ascii=False, sort_keys=True)

    assert "新增人民路事故规则" not in first_text
    assert "case_agent_new" not in first_text
    assert "新增人民路事故规则" in second_text
    assert "case_agent_new" in second_text


def test_agent_input_mutation_cannot_change_shared_or_audit_grounding_snapshot(
    isolated,
    app_client,
    monkeypatch,
):
    _prepare_grounded_event(isolated)
    did_mutate = False

    async def mutating_agent(agent_name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal did_mutate
        if not did_mutate:
            did_mutate = True
            ctx["groundedContext"]["currentEvent"]["eventId"] = "MUTATED_EVENT"
            ctx["groundedContext"].setdefault("groundingRefs", []).append({
                "type": "knowledge_evidence",
                "evidenceId": "MUTATED_REF",
            })
            ctx.setdefault("groundingEvidenceRefs", []).append({
                "type": "knowledge_evidence",
                "evidenceId": "MUTATED_REF",
            })
        return {
            "agentName": agent_name,
            "findings": [f"{agent_name} 本地输入被改动后仍不能污染共享审计"],
            "confidence": 0.8,
            "suggestion": "保持原始 Grounding 审计快照",
            "urgency": "medium",
        }

    _, run, _ = _run_grounded_stream(
        app_client,
        isolated,
        monkeypatch,
        agent_impl=mutating_agent,
    )
    tasks = isolated["collabRepo"].list_tasks(run["run_id"])
    grounding = _json_field(run["grounding_context"], {})
    serialized = json.dumps({"run": run, "tasks": tasks}, ensure_ascii=False, sort_keys=True)

    assert grounding["currentEvent"]["eventId"] == "E_AGENT_GROUNDED"
    assert "MUTATED_EVENT" not in serialized
    assert "MUTATED_REF" not in serialized


def test_location_reresolution_after_run_does_not_rewrite_persisted_snapshot(
    isolated,
    app_client,
    monkeypatch,
):
    _prepare_grounded_event(isolated)
    _, first_run, _ = _run_grounded_stream(app_client, isolated, monkeypatch)
    first_snapshot = _json_field(first_run["grounding_context"], {})
    assert first_snapshot["regionalContext"]["location"]["intersectionId"] == "INT_A_PEOPLE_LIBERATION"

    _bind_event(
        isolated["regionalRepo"],
        "E_AGENT_GROUNDED",
        road_id="ROAD_A_YOUTH",
        intersection_id="INT_A_YOUTH",
        re_resolve=True,
    )
    _, second_run, _ = _run_grounded_stream(app_client, isolated, monkeypatch)

    first_reloaded = isolated["collabRepo"].get_run(first_run["run_id"])
    assert _json_field(first_reloaded["grounding_context"], {}) == first_snapshot
    second_snapshot = _json_field(second_run["grounding_context"], {})
    assert second_snapshot["regionalContext"]["location"]["intersectionId"] == "INT_A_YOUTH"
    assert second_snapshot["regionalContext"]["location"]["roadId"] == "ROAD_A_YOUTH"


def test_legacy_collaboration_schema_reads_and_upgrades_grounding_column(tmp_path, monkeypatch):
    old_db = str(tmp_path / "legacy_collaboration.db")
    monkeypatch.setattr(cfg, "DB_PATH", old_db)
    monkeypatch.setattr(collab_db, "DB_PATH", old_db)
    conn = sqlite3.connect(old_db)
    conn.execute("""
        CREATE TABLE collaboration_runs (
            run_id TEXT PRIMARY KEY, session_id TEXT, trace_id TEXT,
            status TEXT, protocol_version TEXT DEFAULT '1.0',
            normalized_event TEXT DEFAULT '{}',
            selected_agents TEXT DEFAULT '[]', skipped_agents TEXT DEFAULT '[]',
            failed_agents TEXT DEFAULT '[]', budget_usage TEXT DEFAULT '{}',
            final_decision TEXT DEFAULT '', started_at TEXT, updated_at TEXT, completed_at TEXT
        )
    """)
    conn.execute(
        """
        INSERT INTO collaboration_runs (
            run_id, session_id, trace_id, status, protocol_version,
            normalized_event, selected_agents, skipped_agents, failed_agents,
            budget_usage, final_decision, started_at, updated_at, completed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "legacy_run",
            "sess_legacy",
            "trace_legacy",
            "completed",
            "1.0",
            json.dumps({"eventId": "E_LEGACY"}, ensure_ascii=False),
            "[]",
            "[]",
            "[]",
            "{}",
            "{}",
            "2026-06-01T00:00:00",
            "2026-06-01T00:00:00",
            "",
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteCollaborationRepository()
    legacy = repo.get_run("legacy_run")
    assert legacy["run_id"] == "legacy_run"
    assert _json_field(legacy["normalized_event"], {})["eventId"] == "E_LEGACY"

    repo.save_run({
        "run_id": "new_grounded_run",
        "session_id": "sess_legacy",
        "trace_id": "trace_new",
        "status": "completed",
        "normalized_event": {"eventId": "E_NEW"},
        "selected_agents": ["AccidentAgent"],
        "skipped_agents": [],
        "failed_agents": [],
        "budget_usage": {},
        "final_decision": {},
        "started_at": "2026-06-02T00:00:00",
        "completed_at": "",
        "previous_run_context": None,
        "grounding_context": {
            "groundingStatus": "MINIMAL",
            "currentEvent": {"eventId": "E_NEW"},
        },
    })

    conn = sqlite3.connect(old_db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(collaboration_runs)").fetchall()]
    conn.close()
    assert "previous_run_context" in columns
    assert "grounding_context" in columns
    assert _json_field(repo.get_run("legacy_run")["grounding_context"], {}) == {}
    assert _json_field(repo.get_run("new_grounded_run")["grounding_context"], {})["currentEvent"]["eventId"] == "E_NEW"


def test_missing_authoritative_event_does_not_start_minimal_agent(app_client, isolated):
    response = app_client.post("/agent/routed_analyze/stream", json={
        "eventId": "E_AGENT_MISSING",
        "content": "不存在的事件不能降级启动 Agent",
        "contextPolicy": "fresh_event",
    })

    assert response.status_code == 404
    assert isolated["collabRepo"].count_runs_by_event_id("E_AGENT_MISSING") == 0


def test_failed_agent_run_retains_analysis_time_grounding_audit(
    isolated,
    app_client,
    monkeypatch,
):
    _prepare_grounded_event(isolated)

    async def failing_agent(agent_name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError(f"{agent_name} provider down")

    monkeypatch.setattr("backend.agent.collaboration.executor._call_agent_function", failing_agent)
    response = app_client.post("/agent/routed_analyze/stream", json={
        "eventId": "E_AGENT_GROUNDED",
        "content": "请基于真实事件做协同研判",
        "contextPolicy": "fresh_event",
    })
    assert response.status_code == 200
    assert "event: run_failed" in response.text
    run = _run_from_response(response.text, isolated["collabRepo"], "E_AGENT_GROUNDED")
    grounding = _json_field(run["grounding_context"], {})

    assert run["status"] == "failed"
    assert grounding["groundingStatus"] == "FULL"
    assert grounding["currentEvent"]["eventId"] == "E_AGENT_GROUNDED"


def test_grounded_stream_continues_with_minimal_snapshot_when_optional_grounding_fails(
    isolated,
    app_client,
    monkeypatch,
):
    _seed_event("E_AGENT_MINIMAL", analyzed_at="2026-06-30T08:00:00Z")

    class RaisingAssembler:
        def assemble(self, *args, **kwargs):
            raise RuntimeError("grounding service failed")

    monkeypatch.setattr("backend.grounding.assembler.GroundedEventContextAssembler", RaisingAssembler)
    _, run, captured = _run_grounded_stream(
        app_client,
        isolated,
        monkeypatch,
        event_id="E_AGENT_MINIMAL",
    )
    grounding = _json_field(run["grounding_context"], {})

    assert run["status"] == "completed"
    assert grounding["groundingStatus"] == "MINIMAL"
    assert grounding["currentEvent"]["eventId"] == "E_AGENT_MINIMAL"
    assert grounding["regionalContext"]["reason"] == "GROUNDING_ASSEMBLY_ERROR"
    assert captured["AccidentAgent"]["groundedContext"]["groundingStatus"] == "MINIMAL"


def test_grounded_vs_ungrounded_result_contract_differs(monkeypatch):
    async def scenario():
        async def fake_agent_call(agent_name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "agentName": agent_name,
                "findings": ["基础研判"],
                "confidence": 0.7,
                "suggestion": "继续观察",
                "urgency": "medium",
            }

        monkeypatch.setattr("backend.agent.collaboration.executor._call_agent_function", fake_agent_call)
        event = {
            "eventId": "E_DIFF",
            "eventType": "accident",
            "eventTypeCn": "事故",
            "roadName": "人民路",
            "avgSpeed": 8,
            "queueLength": 220,
        }

        ungrounded_state = CollaborationRunState("run_ungrounded", "sess_diff", "trace_diff")
        ungrounded_state.normalized_event = dict(event)
        ungrounded_result = await execute_single_agent(
            AgentTaskNode("task_accident", "run_ungrounded", "AccidentAgent", "analyze"),
            ungrounded_state,
            ExecutionBudget(max_agents=4, max_agent_calls=4),
        )

        grounded_state = CollaborationRunState("run_grounded", "sess_diff", "trace_diff")
        grounded_state.normalized_event = dict(event)
        grounded_state.grounding_context = {
            "groundingStatus": "FULL",
            "assembledAt": "2026-06-30T08:01:00Z",
            "currentEvent": {"eventId": "E_DIFF"},
            "regionalContext": {
                "status": "READY",
                "region": {"regionId": "TEST_REGION_A", "name": "测试区域A"},
                "location": {
                    "regionId": "TEST_REGION_A",
                    "roadId": "ROAD_A_PEOPLE",
                    "intersectionId": "INT_A",
                    "roadName": "人民路",
                    "intersectionName": "人民路路口",
                },
            },
            "historicalContext": {
                "status": "READY",
                "eventCount": 2,
                "unclosedCount": 1,
                "maxRisk": 96,
                "window": {"asOf": "2026-06-30T08:00:00Z"},
            },
            "knowledgeContext": {
                "status": "READY",
                "evidence": [{"evidenceId": "ev1", "documentId": "doc1", "chunkId": "chunk1"}],
            },
            "caseMemoryContext": {
                "status": "READY",
                "cases": [{"caseId": "case1", "sourceWorkflowRunId": "wfrun_case1"}],
            },
            "groundingRefs": [
                {"type": "knowledge_evidence", "evidenceId": "ev1", "documentId": "doc1", "chunkId": "chunk1"},
                {"type": "case_memory", "caseId": "case1", "sourceWorkflowRunId": "wfrun_case1"},
            ],
        }
        grounded_result = await execute_single_agent(
            AgentTaskNode("task_accident", "run_grounded", "AccidentAgent", "analyze"),
            grounded_state,
            ExecutionBudget(max_agents=4, max_agent_calls=4),
        )

        assert ungrounded_result.success is True
        assert grounded_result.success is True
        ungrounded_payload = ungrounded_result.result.model_dump()
        grounded_payload = grounded_result.result.model_dump()
        assert not ungrounded_payload["evidence_refs"]
        assert not any("GroundedEventContext" in item for item in ungrounded_payload["findings"])
        assert any(ref["type"] == "knowledge_evidence" for ref in grounded_payload["evidence_refs"])
        assert any(ref["type"] == "case_memory" for ref in grounded_payload["evidence_refs"])
        assert any("GroundedEventContext" in item for item in grounded_payload["findings"])
        assert grounded_payload["assumptions"]

    asyncio.run(scenario())
