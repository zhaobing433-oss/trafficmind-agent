"""Materialize an isolated, deterministic Qiantang Pilot demo runtime.

The tool reuses production repositories and services. It never points them at
the production database or production RAG/vector stores.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from backend.tools.qiantang_demo_runtime import (
    BACKEND_DIR,
    DEFAULT_RUNTIME_DIR,
    DEMO_PACK_DIR,
    configure_demo_environment,
    ensure_isolated_runtime,
)


REGION_ID = "QT_BY_XIASHA_PILOT_001"
REGION_PACK = BACKEND_DIR / "data" / "pilot_regions" / "qt_by_xiasha_pilot_001"
KNOWLEDGE_PACK = BACKEND_DIR / "data" / "pilot_knowledge" / "qt_by_xiasha_pilot_001"
SYNTHETIC_HISTORY_PACK = BACKEND_DIR / "data" / "pilot_history" / "qt_by_xiasha_pilot_001"
PUBLIC_HISTORY_PACK = BACKEND_DIR / "data" / "pilot_history_public" / "qt_by_xiasha_pilot_001"
HOLDOUT_PACK = BACKEND_DIR / "data" / "pilot_holdout" / "qt_by_xiasha_pilot_001"
MANIFEST_PATH = DEMO_PACK_DIR / "demo_manifest.json"
REPLAY_START = datetime(2026, 9, 4, 13, 0, 0, tzinfo=timezone.utc)
PUBLIC_HISTORY_RECORD_START = datetime(2026, 9, 1, 1, 0, 0, tzinfo=timezone.utc)
LEGACY_VALUES = ("人民路", "中山路", "演示大道", "string", "test")


class FrozenDateTime(datetime):
    current = REPLAY_START

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        value = cls.current
        if tz is not None:
            return value.astimezone(tz)
        return value.astimezone(timezone.utc).replace(tzinfo=None)


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_map() -> Dict[str, Dict[str, Any]]:
    return {
        item["sourceId"]: item
        for item in _load(PUBLIC_HISTORY_PACK / "source_register.json")["sources"]
    }


def _event_standard(event: Dict[str, Any], *, public_source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    keys = (
        "eventId", "eventType", "eventTypeCn", "roadName", "direction", "avgSpeed",
        "queueLength", "duration", "vehicleCount", "confidence", "weather", "timePeriod",
        "isMainRoad", "nearbySchool", "nearbyHospital",
    )
    standard = {key: event[key] for key in keys if key in event}
    if public_source is not None:
        standard["provenance"] = {
            "sourceType": "real_public_reported_incident",
            "datasetReality": "real_public_reported_incident_history",
            "sourceId": event["sourceId"],
            **{
                key: public_source[key]
                for key in (
                    "sourceUri", "sourceTitle", "sourceAuthority", "sourceTier",
                    "sourcePublishedAt",
                )
                if key in public_source
            },
            "sourceDocumentType": public_source.get("sourceType", ""),
        }
        standard["publicIncident"] = {
            key: event[key]
            for key in (
                "occurredAt", "occurredAtPrecision", "locationText", "participantCategory",
                "impactSummary", "responsibilitySummary", "canonicalBinding",
            )
            if key in event
        }
        return standard
    raw = event.get("rawEvent") if isinstance(event.get("rawEvent"), dict) else {}
    if isinstance(raw.get("provenance"), dict):
        standard["provenance"] = raw["provenance"]
    return standard


def _save_event(
    event: Dict[str, Any],
    *,
    analyzed_at: str,
    public_source: Optional[Dict[str, Any]] = None,
) -> bool:
    from backend.tools import db_tools

    if db_tools.get_event_by_id(event["eventId"]) is not None:
        return False
    FrozenDateTime.current = _parse(analyzed_at)
    risk_score = event.get("riskScore", 0)
    risk_level = event.get("riskLevel", "未评估" if public_source else "")
    status = event.get("status", "历史记录" if public_source else "待研判")
    result = {
        "eventId": event["eventId"],
        "standardEvent": _event_standard(event, public_source=public_source),
        "riskScore": risk_score,
        "riskLevel": risk_level,
        "status": status,
        "report": (
            "公开历史交通事件级事实；TrafficMind 未记录当年处置方案或业务结果。"
            if public_source
            else "钱塘 Pilot 合成验证事件。"
        ),
        "analyzedAt": analyzed_at,
    }
    if public_source:
        result["publicIncident"] = result["standardEvent"]["publicIncident"]
        result["sourceProvenance"] = result["standardEvent"]["provenance"]
    if not db_tools.save_event_analysis(result):
        raise RuntimeError(f"failed to save event {event['eventId']}")
    return True


def _resolve_events(repository: Any, events: Iterable[Dict[str, Any]]) -> None:
    from backend.regional.resolver import EventLocationBindingService

    service = EventLocationBindingService(repository)
    for event in events:
        event_id = event["eventId"]
        existing = repository.get_active_event_location_binding(event_id)
        if existing:
            continue
        result = service.resolve_and_bind(event_id, region_id=REGION_ID)
        binding = result.get("binding")
        if not binding or result.get("resolution", {}).get("status") != "resolved":
            raise RuntimeError(f"canonical location unresolved for {event_id}")


def _run_id_from_sse(text: str, collaboration_repository: Any, event_id: str) -> Dict[str, Any]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == "event: run_created" and index + 1 < len(lines):
            payload = lines[index + 1]
            if payload.startswith("data: "):
                run_id = json.loads(payload[6:])["runId"]
                run = collaboration_repository.get_run(run_id)
                if run:
                    return run
    rows = collaboration_repository.list_runs_by_event_id(event_id, limit=1)
    if not rows:
        raise RuntimeError(f"agent run missing for {event_id}")
    return rows[0]


async def _drain(generator: Any) -> List[str]:
    return [item async for item in generator]


def _workflow_run_id(events: List[str]) -> str:
    for event in events:
        if "event: workflow_started" not in event:
            continue
        for line in event.splitlines():
            if line.startswith("data: "):
                value = json.loads(line[6:]).get("runId")
                if value:
                    return str(value)
    raise RuntimeError("workflow run id missing")


def _install_deterministic_validation_runtime(app_module: Any) -> None:
    import backend.agent.collaboration.db_repository as collaboration_db
    import backend.agent.collaboration.executor as collaboration_executor
    import backend.agent.collaboration.orchestrator as orchestrator_module
    import backend.case_memory.models as case_models
    import backend.planning.models as planning_models
    import backend.tools.db_tools as db_tools
    import backend.workflow.executor as workflow_executor
    import backend.workflow.models as workflow_models
    import backend.workflow.nodes.action as action_module
    import backend.workflow.state as workflow_state

    for module in (
        app_module, collaboration_db, case_models, planning_models, db_tools,
        workflow_executor, workflow_models, workflow_state,
    ):
        if hasattr(module, "datetime"):
            module.datetime = FrozenDateTime
    app_module.LLM_ENABLED = False
    orchestrator_module.LLM_ENABLED = False

    async def deterministic_agent(agent_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        event_id = context["groundedContext"]["currentEvent"]["eventId"]
        return {
            "agentName": agent_name,
            "findings": [f"{agent_name} 完成 Pilot 确定性系统回放研判"],
            "confidence": 0.86,
            "suggestion": "建议进入人工审批的验证闭环",
            "urgency": "high",
            "proposed_actions": [{
                "actionType": "notify_wechat",
                "params": {"message": f"{event_id} deterministic validation replay"},
            }],
        }

    collaboration_executor._call_agent_function = deterministic_agent
    original_dispatch = action_module._dispatch_action

    # Keep source event records immutable while validating the Workflow action path.
    async def safe_dispatch(action_type: str, params: Dict[str, Any], state: Any) -> Dict[str, Any]:
        if action_type.startswith("notify_"):
            return {"sent": True, "validationSink": "isolated_demo_no_external_dispatch"}
        if action_type == "save_result":
            return {
                "saved": True,
                "eventId": (state.current_event or {}).get("eventId"),
                "validationSink": "isolated_demo_no_event_overwrite",
            }
        return await original_dispatch(action_type, params, state)

    action_module._dispatch_action = safe_dispatch

    async def memory_noop(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "runId": args[1] if len(args) > 1 else "",
            "sessionId": args[0] if args else "",
            "candidateCount": 0,
            "createdCount": 0,
            "deduplicatedCount": 0,
            "supersededCount": 0,
            "rejectedCount": 0,
            "confirmedCount": 0,
            "latencyMs": 0,
            "traceId": "qiantang_demo_deterministic_noop",
            "writeResults": [],
        }

    app_module._run_memory_extraction = memory_noop


def _tag_case(case_repository: Any, case: Any, reality: str, source_event_reality: str) -> Any:
    existing = case_repository.get_case(case.case_id)
    if existing is None:
        raise RuntimeError(f"case missing after build: {case.case_id}")
    case.source_type = reality
    case.provenance = {
        **case.provenance,
        "caseReality": reality,
        "sourceEventReality": source_event_reality,
        "systemDecisionReality": "deterministic_validation_replay",
        "approvalReality": "validation_decision",
    }
    case.workflow_outcome = {
        **case.workflow_outcome,
        "caseReality": reality,
        "sourceEventReality": source_event_reality,
        "systemDecisionReality": "deterministic_validation_replay",
        "approvalReality": "validation_decision",
        "businessOutcome": {
            "status": "unknown_without_external_evidence",
            "reason": "system replay status is not an observed traffic outcome",
        },
    }
    return case_repository.update_case_preserving_identity(existing, case)


def _materialize_case(
    *,
    client: Any,
    event: Dict[str, Any],
    decision: str,
    reality: str,
    source_event_reality: str,
    replay_index: int,
    collaboration_repository: Any,
    workflow_repository: Any,
    case_repository: Any,
    case_service: Any,
) -> Any:
    existing = [case for case in case_repository.list_cases_for_source_event(event["eventId"]) if case.source_type == reality]
    if existing:
        return existing[0]

    from backend.planning.api import PlanRunRequest, _load_plan_from_metadata, _resolve_plan_run_event
    from backend.workflow.executor import WorkflowExecutor

    FrozenDateTime.current = REPLAY_START + timedelta(seconds=replay_index)
    response = client.post("/agent/routed_analyze/stream", json={
        "eventId": event["eventId"],
        "content": "请基于当前事件、区域、历史、知识和案例执行确定性 Pilot 系统回放研判",
        "contextPolicy": "fresh_event",
    })
    if response.status_code != 200 or "event: run_completed" not in response.text:
        raise RuntimeError(f"agent replay failed for {event['eventId']}: {response.text[:500]}")
    agent_run = _run_id_from_sse(response.text, collaboration_repository, event["eventId"])
    plan_response = client.post("/planning/plans/from-agent", json={
        "eventId": event["eventId"],
        "sessionId": agent_run["session_id"],
        "collaborationRunId": agent_run["run_id"],
    })
    if plan_response.status_code != 200:
        raise RuntimeError(f"plan materialization failed for {event['eventId']}: {plan_response.text[:500]}")
    plan_body = plan_response.json()
    definition = workflow_repository.get_definition(plan_body["planId"])
    if definition is None:
        raise RuntimeError(f"workflow definition missing for {event['eventId']}")
    plan = _load_plan_from_metadata(definition.metadata)
    if plan is None:
        raise RuntimeError(f"plan metadata missing for {event['eventId']}")
    initial_event = _resolve_plan_run_event(
        plan,
        PlanRunRequest(event={}, sessionId=agent_run["session_id"], triggeredBy="qiantang_demo_materializer"),
    )
    executor = WorkflowExecutor(repository=workflow_repository)
    started = asyncio.run(_drain(executor.start(
        definition.id,
        session_id=agent_run["session_id"],
        initial_event=initial_event,
        triggered_by="qiantang_demo_materializer",
    )))
    workflow_run_id = _workflow_run_id(started)
    if decision == "approve":
        asyncio.run(executor.approve(
            workflow_run_id,
            reviewer="Pilot deterministic validation policy",
            comment="Pre-frozen validation decision: approve",
        ))
        asyncio.run(_drain(executor.resume(workflow_run_id)))
    elif decision == "reject":
        asyncio.run(executor.reject(
            workflow_run_id,
            reviewer="Pilot deterministic validation policy",
            comment="Pre-frozen validation decision: reject",
        ))
    else:
        raise ValueError(f"unsupported approval decision: {decision}")
    built = case_service.build_from_workflow_run(workflow_run_id).case
    return _tag_case(case_repository, built, reality, source_event_reality)


def _database_snapshot(database: Path) -> Dict[str, Any]:
    tables = (
        "event_records", "event_location_bindings", "collaboration_runs", "workflow_definitions",
        "workflow_runs", "workflow_approvals", "traffic_case_memories",
    )
    payload: Dict[str, Any] = {}
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        available = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in tables:
            if table not in available:
                payload[table] = []
                continue
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            payload[table] = sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "counts": {table: len(rows) for table, rows in payload.items()},
    }


def _legacy_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT eventId, eventType, eventTypeCn, roadName, status FROM event_records").fetchall()
    return sum(
        1
        for row in rows
        if any(value.lower() in str(field or "").lower() for value in LEGACY_VALUES for field in row)
    )


def materialize(runtime_dir: Path, *, reset: bool = False) -> Dict[str, Any]:
    runtime_dir = ensure_isolated_runtime(runtime_dir)
    if reset and runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    configure_demo_environment(runtime_dir)

    import backend.agent.collaboration.db_repository as collaboration_db
    import backend.chat.chat_db as chat_db
    import backend.config as config
    import backend.rag.v2.document_repository as document_repository
    import backend.rag.v2.pipeline as rag_pipeline
    import backend.rag.v2.sparse_index as sparse_index
    import backend.tools.db_tools as db_tools
    from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository, init_collaboration_tables
    from backend.case_memory.repository import SQLiteCaseMemoryRepository, init_case_memory_tables
    from backend.case_memory.service import TrafficCaseMemoryService
    from backend.memory.store import init_memory_tables
    from backend.rag.v2.providers import get_embedding_provider
    from backend.regional.importer import load_context_pack_from_directory
    from backend.regional.repository import SQLiteRegionalRepository, init_regional_tables
    from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables

    expected_db = (runtime_dir / "trafficmind_demo.db").resolve()
    if Path(config.DB_PATH).resolve() != expected_db:
        raise RuntimeError(f"demo path isolation failed: {config.DB_PATH}")
    db_tools.DB_PATH = str(expected_db)
    chat_db.DB_PATH = str(expected_db)
    collaboration_db.DB_PATH = str(expected_db)
    db_tools.datetime = FrozenDateTime
    collaboration_db.datetime = FrozenDateTime

    db_tools.init_db()
    chat_db.reset_initialized()
    chat_db.init_chat_tables()
    init_memory_tables()
    init_workflow_tables()
    init_collaboration_tables()
    init_regional_tables(db_path=str(expected_db))
    init_case_memory_tables()
    sparse_index.init_fts()
    document_repository.init_db()
    rag_pipeline.reset_pipeline()

    provider = get_embedding_provider()
    dimension = provider.get_dimension()
    resolved_model = provider.get_resolved_model_name()
    if provider.is_degraded() or resolved_model != "Qwen/Qwen3-Embedding-0.6B" or dimension != 1024:
        raise RuntimeError(
            f"Qwen embedding provider unavailable: model={resolved_model}, dim={dimension}, "
            f"degraded={provider.is_degraded()}, reason={provider.get_degraded_reason()}"
        )

    regional_repository = SQLiteRegionalRepository(db_path=str(expected_db))
    if regional_repository.get_region(REGION_ID) is None:
        regional_repository.import_context_pack(load_context_pack_from_directory(REGION_PACK))

    from backend.knowledge.service import create_document

    knowledge_documents = _load(KNOWLEDGE_PACK / "documents.json")
    for document in knowledge_documents:
        create_document(
            name=document["title"],
            doc_type=document["docType"],
            content=document["content"],
            metadata=document["metadata"],
        )

    synthetic_history = _load(SYNTHETIC_HISTORY_PACK / "events.json")["events"]
    for event in synthetic_history:
        _save_event(event, analyzed_at=event.get("createdAt") or event["updatedAt"])
    _resolve_events(regional_repository, synthetic_history)

    public_sources = _source_map()
    public_history = _load(PUBLIC_HISTORY_PACK / "events.json")["events"]
    for index, event in enumerate(public_history):
        recorded_at = (PUBLIC_HISTORY_RECORD_START + timedelta(minutes=index)).isoformat().replace("+00:00", "Z")
        _save_event(event, analyzed_at=recorded_at, public_source=public_sources[event["sourceId"]])
    _resolve_events(regional_repository, public_history)

    import backend.app as app_module
    from fastapi.testclient import TestClient

    _install_deterministic_validation_runtime(app_module)
    collaboration_repository = SQLiteCollaborationRepository()
    workflow_repository = SQLiteWorkflowRepository()
    case_repository = SQLiteCaseMemoryRepository()
    case_service = TrafficCaseMemoryService(
        repository=case_repository,
        regional_repo=regional_repository,
    )
    manifest = _load(MANIFEST_PATH)
    synthetic_by_id = {event["eventId"]: event for event in synthetic_history}
    public_by_id = {event["eventId"]: event for event in public_history}
    with TestClient(app_module.app) as client:
        for index, event_id in enumerate(manifest["syntheticClosureSeedEventIds"]):
            _materialize_case(
                client=client,
                event=synthetic_by_id[event_id],
                decision="approve" if index % 2 == 0 else "reject",
                reality="synthetic_event_system_closure",
                source_event_reality="synthetic_validation",
                replay_index=index,
                collaboration_repository=collaboration_repository,
                workflow_repository=workflow_repository,
                case_repository=case_repository,
                case_service=case_service,
            )
        for index, item in enumerate(manifest["publicReplay"], start=len(manifest["syntheticClosureSeedEventIds"])):
            _materialize_case(
                client=client,
                event=public_by_id[item["eventId"]],
                decision=item["decision"],
                reality="public_incident_replay_system_closure",
                source_event_reality="real_public_reported_incident",
                replay_index=index,
                collaboration_repository=collaboration_repository,
                workflow_repository=workflow_repository,
                case_repository=case_repository,
                case_service=case_service,
            )

    holdout = _load(HOLDOUT_PACK / "holdout_events.json")["events"]
    holdout_by_id = {event["eventId"]: event for event in holdout}
    current_events = [holdout_by_id[event_id] for event_id in manifest["currentEventIds"]]
    for event in current_events:
        _save_event(event, analyzed_at=event.get("createdAt") or event["updatedAt"])
    _resolve_events(regional_repository, current_events)

    cases = [
        case
        for event_id in manifest["syntheticClosureSeedEventIds"]
        for case in case_repository.list_cases_for_source_event(event_id)
        if case.source_type == "synthetic_event_system_closure"
    ]
    public_cases = [
        case
        for item in manifest["publicReplay"]
        for case in case_repository.list_cases_for_source_event(item["eventId"])
        if case.source_type == "public_incident_replay_system_closure"
    ]
    retrieval = case_service.get_case_context_for_event(current_events[0]["eventId"], limit=10)
    retrieval_types = {case["sourceType"] for case in retrieval["cases"]}
    wrong_region = case_repository.find_context_candidates(
        region_id="QT_OUTSIDE_PILOT",
        event_type=current_events[0]["eventType"],
        road_id=None,
        intersection_id=None,
        as_of=current_events[0]["createdAt"],
        limit=10,
    )
    future_leakage = case_repository.find_context_candidates(
        region_id=REGION_ID,
        event_type=current_events[0]["eventType"],
        road_id=None,
        intersection_id=None,
        as_of=REPLAY_START.isoformat().replace("+00:00", "Z"),
        limit=10,
    )
    snapshot = _database_snapshot(expected_db)
    report = {
        "demoId": manifest["demoId"],
        "runtimeDir": str(runtime_dir),
        "database": str(expected_db),
        "embedding": {
            "model": provider.get_model_name(),
            "resolvedModel": resolved_model,
            "dimension": dimension,
            "degraded": provider.is_degraded(),
        },
        "knowledgeDocumentCount": len(knowledge_documents),
        "publicHistoryEventCount": len(public_history),
        "syntheticClosureCaseCount": len(cases),
        "syntheticClosureStatusCounts": dict(Counter(case.final_status for case in cases)),
        "publicReplayCaseCount": len(public_cases),
        "publicReplayStatusCounts": dict(Counter(case.final_status for case in public_cases)),
        "currentEventCount": len(current_events),
        "currentEventTypeCount": len({event["eventType"] for event in current_events}),
        "currentCanonicalLocationCount": len({
            event["validation"]["expectedCanonicalLocation"].get("intersectionId")
            or event["validation"]["expectedCanonicalLocation"].get("roadId")
            for event in current_events
        }),
        "legacyTestEventCount": _legacy_count(expected_db),
        "memoryRetrieval": {
            "targetEventId": current_events[0]["eventId"],
            "asOf": current_events[0]["createdAt"],
            "caseRealityTypes": sorted(retrieval_types),
            "publicReplayRetrievable": "public_incident_replay_system_closure" in retrieval_types,
            "syntheticClosureRetrievable": "synthetic_event_system_closure" in retrieval_types,
            "wrongRegionCount": wrong_region["total"],
            "futureLeakageCount": future_leakage["total"],
        },
        "businessSnapshot": snapshot,
    }
    (runtime_dir / "materialization_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize the isolated Qiantang Pilot demo runtime")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--reset", action="store_true", help="delete and rebuild only the isolated demo runtime")
    args = parser.parse_args()
    report = materialize(args.runtime_dir, reset=args.reset)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
