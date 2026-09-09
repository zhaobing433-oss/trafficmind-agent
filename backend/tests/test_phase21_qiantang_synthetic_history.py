"""Phase21 G3-A Qiantang synthetic historical grounding pool validation.

The formal G3-A pack is deterministic synthetic validation history over the
real G1 pilot geography. Tests import into temporary SQLite/RAG/Chroma/FTS
stores only and must not create Agent runs, plans, workflow runs, approvals, or
case memories.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
import backend.tools.db_tools as db_tools
from backend.case_memory.repository import init_case_memory_tables
from backend.config import EVENT_BASE_SCORES, EVENT_STATUSES, RISK_LEVELS
from backend.regional.historical import HistoricalTrafficService, TIME_OF_DAY_BUCKETS
from backend.regional.importer import load_context_pack_from_directory
from backend.regional.repository import SQLiteRegionalRepository
from backend.regional.resolver import EventLocationBindingService
from backend.tools.alert_tools import UNCLOSED_STATUSES


REGION_ID = "QT_BY_XIASHA_PILOT_001"
DATASET_ID = "QT_BY_XIASHA_SYNTH_HISTORY_001"
DATASET_VERSION = "1.0.0"
HISTORY_PACK_DIR = Path(__file__).resolve().parents[1] / "data" / "pilot_history" / "qt_by_xiasha_pilot_001"
REGION_PACK_DIR = Path(__file__).resolve().parents[1] / "data" / "pilot_regions" / "qt_by_xiasha_pilot_001"
KNOWLEDGE_PACK_DIR = Path(__file__).resolve().parents[1] / "data" / "pilot_knowledge" / "qt_by_xiasha_pilot_001"
PRODUCTION_DB = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
SAFE_G3_FROM = "2024-08-01T00:00:00Z"
HISTORY_UPPER_BOUND = "2026-08-31T23:00:00Z"
TARGET_AS_OF = "2026-08-31T23:30:00Z"
ANSWER_LABEL_KEYS = {
    "expectedRecommendation",
    "expectedPlan",
    "expectedAction",
    "correctAnswer",
    "groundTruthAction",
    "bestStrategy",
    "preferredWorkflow",
    "shouldUseKnowledgeDoc",
    "shouldRetrieveCase",
    "answer",
    "recommendation",
    "caseSeedReason",
    "holdoutGroup",
    "modelPrompt",
    "hiddenLabel",
}
AGENT_PLAN_WORKFLOW_CASE_KEYS = {
    "agentAnalysis",
    "agentResult",
    "plan",
    "planId",
    "workflowRun",
    "workflowRunId",
    "approval",
    "caseMemory",
    "caseId",
}
OPTIONAL_CONTEXT_FIELDS_NOT_IN_FORMAL_EVENTS = {"isMainRoad", "nearbySchool", "nearbyHospital"}
TIME_PERIOD_TO_BUCKET = {
    "night": "00-06",
    "morning_peak": "06-12",
    "afternoon": "12-18",
    "evening_peak": "18-24",
}


class FixedDateTime(datetime):
    current = datetime(2026, 8, 31, 23, 45, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        value = cls.current
        if tz is not None:
            return value.astimezone(tz)
        return value.astimezone(timezone.utc).replace(tzinfo=None)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_history_pack() -> Dict[str, Any]:
    return {
        "package": _load_json(HISTORY_PACK_DIR / "package.json"),
        "events": _load_json(HISTORY_PACK_DIR / "events.json")["events"],
        "generationSpec": _load_json(HISTORY_PACK_DIR / "generation_spec.json"),
    }


def _load_g1_pack() -> Dict[str, Any]:
    return {
        "roads": _load_json(REGION_PACK_DIR / "roads.json"),
        "intersections": _load_json(REGION_PACK_DIR / "intersections.json"),
    }


def _load_g2_documents() -> List[Dict[str, Any]]:
    return _load_json(KNOWLEDGE_PACK_DIR / "documents.json")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_local(value: str) -> datetime:
    return _parse_utc(value).astimezone(ZoneInfo("Asia/Shanghai"))


def _parse_persisted_time(value: str) -> datetime:
    if "T" in value:
        return _parse_utc(value)
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _bucket(value: datetime) -> str:
    hour = value.hour
    if hour < 6:
        return "00-06"
    if hour < 12:
        return "06-12"
    if hour < 18:
        return "12-18"
    return "18-24"


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _location_key(event: Dict[str, Any]) -> tuple[str, str]:
    validation = event["validation"]
    expected = validation["expectedCanonicalLocation"]
    if validation["locationGranularity"] == "intersection":
        return ("intersection", expected["intersectionId"])
    return ("road", expected["roadId"])


def _save_event(event: Dict[str, Any]) -> None:
    standard_event = {
        key: event[key]
        for key in (
            "eventId",
            "eventType",
            "eventTypeCn",
            "roadName",
            "direction",
            "avgSpeed",
            "queueLength",
            "duration",
            "vehicleCount",
            "confidence",
            "weather",
            "timePeriod",
            "isMainRoad",
            "nearbySchool",
            "nearbyHospital",
        )
        if key in event
    }
    standard_event["provenance"] = event["rawEvent"]["provenance"]
    FixedDateTime.current = _parse_utc(event.get("updatedAt", event["createdAt"]))
    assert db_tools.save_event_analysis({
        "eventId": event["eventId"],
        "standardEvent": standard_event,
        "riskScore": event["riskScore"],
        "riskLevel": event["riskLevel"],
        "status": event["status"],
        "report": "Phase21 G3-A synthetic validation history event.",
        "analyzedAt": event["createdAt"],
    })


def _import_events(events: List[Dict[str, Any]]) -> int:
    before = _table_count(cfg.DB_PATH, "event_records")
    for event in events:
        _save_event(event)
    return _table_count(cfg.DB_PATH, "event_records") - before


def _resolve_events(repo: SQLiteRegionalRepository, events: List[Dict[str, Any]]) -> Dict[str, int]:
    binder = EventLocationBindingService(repo)
    unresolved = 0
    ambiguous = 0
    for event in events:
        result = binder.resolve_and_bind(event["eventId"], region_id=REGION_ID)
        resolution = result["resolution"]
        if resolution["status"] == "unresolved":
            unresolved += 1
        if resolution["status"] == "ambiguous":
            ambiguous += 1
        expected = event["validation"]["expectedCanonicalLocation"]
        assert resolution["regionId"] == expected["regionId"]
        assert resolution.get("roadId") == expected.get("roadId")
        assert resolution.get("intersectionId") == expected.get("intersectionId")
        assert result["binding"] is not None
    return {"unresolved": unresolved, "ambiguous": ambiguous}


def _import_g2_knowledge() -> None:
    from backend.knowledge.service import create_document

    for document in _load_g2_documents():
        create_document(
            name=document["title"],
            doc_type=document["docType"],
            content=document["content"],
            metadata=document["metadata"],
        )


def _table_count(db_path: str, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row is None:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _active_binding_counts(db_path: str) -> Dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, COUNT(*) AS c
            FROM event_location_bindings
            WHERE status = 'resolved'
            GROUP BY event_id
            """
        ).fetchall()
    return {row[0]: int(row[1]) for row in rows}


def _binding_status_counts(db_path: str) -> Counter:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM event_location_bindings
            GROUP BY status
            """
        ).fetchall()
    return Counter({row[0]: int(row[1]) for row in rows})


def _event_record_snapshots(db_path: str) -> Dict[str, Dict[str, Any]]:
    fields = "eventId, status, rawEvent, fullResult, createdAt, updatedAt, duration, riskScore, riskLevel"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {fields} FROM event_records ORDER BY eventId").fetchall()
    return {row["eventId"]: dict(row) for row in rows}


def _expected_aggregate(
    events: List[Dict[str, Any]],
    *,
    location_key: tuple[str, str],
    start_time: str,
    end_time: str,
    exclude_event_id: str = "",
) -> Dict[str, Any]:
    start = _parse_local(start_time)
    end = _parse_local(end_time)
    scoped = []
    for event in events:
        if event["eventId"] == exclude_event_id:
            continue
        if _location_key(event) != location_key:
            continue
        created = _parse_local(event["createdAt"])
        if start <= created < end:
            scoped.append({**event, "_createdAtParsed": created})

    scoped.sort(key=lambda item: (item["_createdAtParsed"], item["eventId"]), reverse=True)
    durations = [float(event["duration"]) for event in scoped if event.get("duration") is not None]
    return {
        "eventCount": len(scoped),
        "eventTypeDistribution": dict(sorted(Counter(event["eventType"] for event in scoped).items())),
        "riskDistribution": dict(sorted(Counter(event["riskLevel"] for event in scoped).items())),
        "averageDuration": round(sum(durations) / len(durations), 2) if durations else None,
        "durationSampleCount": len(durations),
        "maxRisk": max((float(event["riskScore"]) for event in scoped), default=None),
        "unclosedCount": sum(1 for event in scoped if event["status"] in UNCLOSED_STATUSES),
        "timeOfDayDistribution": {
            bucket: sum(1 for event in scoped if _bucket(event["_createdAtParsed"]) == bucket)
            for bucket in TIME_OF_DAY_BUCKETS
        },
        "recentEventRefs": [event["eventId"] for event in scoped[:5]],
    }


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    event_db = str(tmp_path / "phase21_g3a_events.db")
    rag_db = str(tmp_path / "phase21_g3a_rag.db")
    fts_path = str(tmp_path / "phase21_g3a_fts.db")
    chroma_path = str(tmp_path / "phase21_g3a_chroma")
    assert event_db != PRODUCTION_DB

    monkeypatch.setattr(cfg, "DB_PATH", event_db)
    monkeypatch.setattr(db_tools, "DB_PATH", event_db)
    monkeypatch.setattr(db_tools, "datetime", FixedDateTime)
    db_tools.init_db()
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

    import backend.knowledge.regional_context as knowledge_context

    monkeypatch.setattr(knowledge_context, "get_embedding_provider", lambda: fake_provider)

    sparse_idx.init_fts()
    doc_repo.init_db()

    repo = SQLiteRegionalRepository(db_path=event_db)
    repo.import_context_pack(load_context_pack_from_directory(REGION_PACK_DIR))
    return {
        "tmpRoot": str(tmp_path),
        "eventDb": event_db,
        "ragDb": rag_db,
        "ftsPath": fts_path,
        "chromaPath": chroma_path,
        "repo": repo,
    }


def test_g3a_pack_contract_distribution_and_reality_flags():
    pack = _load_history_pack()
    package = pack["package"]
    events = pack["events"]
    generation_spec = pack["generationSpec"]
    canonical_event_types = set(EVENT_BASE_SCORES)
    canonical_statuses = set(EVENT_STATUSES)
    canonical_risk_levels = {level for _, level in RISK_LEVELS}

    assert package["datasetId"] == DATASET_ID
    assert package["datasetVersion"] == DATASET_VERSION
    assert package["regionId"] == REGION_ID
    assert package["datasetReality"] == "synthetic_validation_history"
    assert package["realGeography"] is True
    assert package["realTrafficEventLogs"] is False
    assert package["realtimeTraffic"] is False
    assert package["officialHistoricalDataset"] is False
    assert package["governmentFeed"] is False
    assert package["holdoutIncluded"] is False
    assert package["caseSeedIncluded"] is False
    assert package["agentRunsIncluded"] is False
    assert package["plansIncluded"] is False
    assert package["workflowRunsIncluded"] is False
    assert package["trafficCaseMemoryIncluded"] is False
    assert package["safeEvaluationRange"]["fromInclusive"] == SAFE_G3_FROM
    assert package["holdoutTimePolicy"]["finalHoldoutTimePrecommitted"] is False
    assert generation_spec["generationSeed"] == "deterministic-formula-no-random-runtime"
    assert generation_spec["eventCount"] == len(events)
    assert generation_spec["distribution"] == package["inventory"]
    assert "omit isMainRoad, nearbySchool, and nearbyHospital" in generation_spec["optionalContextFieldPolicy"]
    assert generation_spec["noGeneratedObjects"] == {
        "holdoutEvents": 0,
        "agentRuns": 0,
        "plans": 0,
        "workflowRuns": 0,
        "caseMemories": 0,
    }

    assert len(events) == 144
    assert len({event["eventId"] for event in events}) == len(events)
    assert [event["eventId"] for event in events] == [
        f"SYN_QT_HIST_{idx:04d}" for idx in range(1, len(events) + 1)
    ]
    assert min(event["createdAt"] for event in events) == package["historyRangeStart"]
    assert max(event["createdAt"] for event in events) == package["historyRangeEnd"]
    assert min(_parse_utc(event["createdAt"]) for event in events) >= _parse_utc(SAFE_G3_FROM)
    assert max(_parse_utc(event["createdAt"]) for event in events) <= _parse_utc(HISTORY_UPPER_BOUND)

    event_type_counts = Counter(event["eventType"] for event in events)
    assert set(event_type_counts) == {
        "accident",
        "congestion",
        "illegal_parking",
        "pedestrian_intrusion",
        "signal_fault",
        "vehicle_stopped",
    }
    assert all(value >= 10 for value in event_type_counts.values())
    assert event_type_counts == Counter(package["inventory"]["eventTypeCounts"])
    assert set(event_type_counts).issubset(canonical_event_types)
    assert set(Counter(event["status"] for event in events)).issubset(canonical_statuses)
    assert set(Counter(event["riskLevel"] for event in events)).issubset(canonical_risk_levels)
    assert all(isinstance(event["riskScore"], int) and 0 <= event["riskScore"] <= 100 for event in events)
    assert any(event["status"] in UNCLOSED_STATUSES for event in events)
    assert any(event["status"] not in UNCLOSED_STATUSES for event in events)

    by_intersection = Counter(
        event["validation"]["expectedCanonicalLocation"]["intersectionId"]
        for event in events
        if event["validation"]["locationGranularity"] == "intersection"
    )
    by_road = Counter(
        event["validation"]["expectedCanonicalLocation"]["roadId"]
        for event in events
        if event["validation"]["locationGranularity"] == "road"
    )
    assert sum(by_intersection.values()) == 108
    assert sum(by_road.values()) == 36
    assert all(value >= 8 for value in by_intersection.values())
    assert len(by_intersection) == 9
    assert len(by_road) >= 5
    assert all(value >= 4 for value in by_road.values())

    for location in by_intersection:
        types = {
            event["eventType"]
            for event in events
            if event["validation"]["expectedCanonicalLocation"]["intersectionId"] == location
        }
        assert len(types) >= 2

    assert sum(1 for event in events if event["duration"] is None) == 0
    assert sum(1 for event in events if event["duration"] is not None) == 144
    assert package["inventory"]["durationFiniteCount"] == 144
    assert package["inventory"]["durationNullCount"] == 0
    assert generation_spec["distribution"]["durationFiniteCount"] == 144
    assert generation_spec["distribution"]["durationNullCount"] == 0
    assert all(
        event["updatedAt"] >= event["createdAt"]
        and event["createdAt"].endswith("Z")
        and event["updatedAt"].endswith("Z")
        for event in events
    )
    assert {event["timePeriod"] for event in events} == {"night", "morning_peak", "afternoon", "evening_peak"}
    assert {_bucket(_parse_local(event["createdAt"])) for event in events} == set(TIME_OF_DAY_BUCKETS)
    assert all(
        TIME_PERIOD_TO_BUCKET[event["timePeriod"]] == _bucket(_parse_local(event["createdAt"]))
        for event in events
    )


def test_every_event_is_machine_synthetic_without_answer_or_execution_labels():
    events = _load_history_pack()["events"]
    for event in events:
        assert event["eventId"].startswith("SYN_QT_HIST_")
        assert event["rawEvent"] == {
            "provenance": {
                "sourceType": "synthetic_validation",
                "datasetId": DATASET_ID,
                "datasetVersion": DATASET_VERSION,
            }
        }
        event_keys = set(_walk_keys(event))
        assert ANSWER_LABEL_KEYS.isdisjoint(event_keys)
        assert AGENT_PLAN_WORKFLOW_CASE_KEYS.isdisjoint(event_keys)
        assert OPTIONAL_CONTEXT_FIELDS_NOT_IN_FORMAL_EVENTS.isdisjoint(event_keys)
        assert "fullResult" not in event
        assert set(event["rawEvent"]) == {"provenance"}
        assert event["validation"]["expectedCanonicalLocation"]["regionId"] == REGION_ID


def test_joint_distributions_do_not_encode_single_answer_patterns():
    events = _load_history_pack()["events"]
    by_location: Dict[str, set[str]] = {}
    by_type_risk: Dict[str, set[str]] = {}
    by_type_status: Dict[str, set[str]] = {}
    by_type_time_bucket: Dict[str, set[str]] = {}
    for event in events:
        expected = event["validation"]["expectedCanonicalLocation"]
        location_id = expected.get("intersectionId") or expected.get("roadId")
        by_location.setdefault(location_id, set()).add(event["eventType"])
        by_type_risk.setdefault(event["eventType"], set()).add(event["riskLevel"])
        by_type_status.setdefault(event["eventType"], set()).add(event["status"])
        by_type_time_bucket.setdefault(event["eventType"], set()).add(_bucket(_parse_local(event["createdAt"])))

    assert all(len(values) >= 2 for values in by_location.values())
    assert all(len(values) >= 2 for values in by_type_risk.values())
    assert all(len(values) >= 2 for values in by_type_status.values())
    assert all(len(values) >= 2 for values in by_type_time_bucket.values())


def test_all_location_texts_are_from_g1_names_or_sourced_aliases():
    events = _load_history_pack()["events"]
    g1 = _load_g1_pack()
    road_texts = set()
    for road in g1["roads"]:
        road_texts.add(road["name"])
        road_texts.update(road.get("aliases") or [])
    intersection_texts = {item["name"] for item in g1["intersections"]}

    for event in events:
        if event["validation"]["locationGranularity"] == "intersection":
            assert event["roadName"] in intersection_texts
            assert event["validation"]["locationTextSource"] == "g1_intersection_name"
        else:
            assert event["roadName"] in road_texts
            assert event["validation"]["locationTextSource"] == "g1_road_name_or_sourced_alias"


def test_import_isolated_idempotent_resolves_all_events_and_persists_one_active_binding(isolated):
    events = _load_history_pack()["events"]
    assert isolated["eventDb"].startswith(isolated["tmpRoot"])
    assert isolated["eventDb"] != PRODUCTION_DB

    first_new = _import_events(events)
    first_snapshot = _event_record_snapshots(isolated["eventDb"])
    second_new = _import_events(events)
    second_snapshot = _event_record_snapshots(isolated["eventDb"])
    assert first_new == len(events)
    assert second_new == 0
    assert second_snapshot == first_snapshot

    resolution_counts = _resolve_events(isolated["repo"], events)
    assert resolution_counts == {"unresolved": 0, "ambiguous": 0}

    active_counts = _active_binding_counts(isolated["eventDb"])
    assert all(active_counts[event["eventId"]] == 1 for event in events)
    assert _binding_status_counts(isolated["eventDb"]) == Counter({"resolved": len(events)})

    with sqlite3.connect(isolated["eventDb"]) as conn:
        conn.row_factory = sqlite3.Row
        sample = conn.execute(
            "SELECT rawEvent, fullResult, duration FROM event_records WHERE eventId = ?",
            ("SYN_QT_HIST_0001",),
        ).fetchone()
        raw = json.loads(sample["rawEvent"])
        full = json.loads(sample["fullResult"])
        assert raw["provenance"]["sourceType"] == "synthetic_validation"
        assert raw["provenance"]["datasetId"] == DATASET_ID
        assert full["eventId"] == "SYN_QT_HIST_0001"
        assert "expectedCanonicalLocation" not in json.dumps(full, ensure_ascii=False)
        assert sample["duration"] == events[0]["duration"]

    assert _table_count(isolated["eventDb"], "traffic_case_memories") == 0
    assert _table_count(isolated["eventDb"], "workflow_runs") == 0
    assert _table_count(isolated["eventDb"], "workflow_definitions") == 0


def test_formal_events_round_trip_business_fields_through_event_repository(isolated):
    events = _load_history_pack()["events"]
    _import_events(events)
    drift = []

    with sqlite3.connect(isolated["eventDb"]) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            row["eventId"]: row
            for row in conn.execute("SELECT * FROM event_records ORDER BY eventId").fetchall()
        }

    for event in events:
        row = rows[event["eventId"]]
        raw = json.loads(row["rawEvent"])
        full = json.loads(row["fullResult"])
        comparisons = {
            "eventId": row["eventId"] == event["eventId"],
            "eventType": row["eventType"] == event["eventType"],
            "eventTypeCn": row["eventTypeCn"] == event["eventTypeCn"],
            "roadName": row["roadName"] == event["roadName"],
            "status": row["status"] == event["status"],
            "createdAt": _parse_persisted_time(row["createdAt"]) == _parse_utc(event["createdAt"]),
            "updatedAt": _parse_persisted_time(row["updatedAt"]) == _parse_utc(event["updatedAt"]),
            "duration": float(row["duration"]) == float(event["duration"]),
            "riskScore": int(row["riskScore"]) == int(event["riskScore"]),
            "riskLevel": row["riskLevel"] == event["riskLevel"],
            "avgSpeed": float(row["avgSpeed"]) == float(event["avgSpeed"]),
            "queueLength": float(row["queueLength"]) == float(event["queueLength"]),
            "weather": row["weather"] == event["weather"],
            "timePeriod": row["timePeriod"] == event["timePeriod"],
            "rawEvent.provenance": raw["provenance"] == event["rawEvent"]["provenance"],
        }
        if not all(comparisons.values()):
            drift.append((event["eventId"], {k: v for k, v in comparisons.items() if not v}))
        assert "expectedCanonicalLocation" not in json.dumps(full, ensure_ascii=False)
        assert OPTIONAL_CONTEXT_FIELDS_NOT_IN_FORMAL_EVENTS.isdisjoint(raw)
        assert ANSWER_LABEL_KEYS.isdisjoint(set(_walk_keys(raw)))

    assert drift == []


def test_historical_service_target_events_and_exact_aggregates(isolated):
    events = _load_history_pack()["events"]
    _import_events(events)
    _resolve_events(isolated["repo"], events)
    historical = HistoricalTrafficService(isolated["repo"])

    target_specs = [
        ("SYN_QT_TARGET_INT_1", "文泽路 × 2号大街", "intersection", "QT_BY_INT_WENZE_NO2"),
        ("SYN_QT_TARGET_INT_2", "高沙路 × 学林街", "intersection", "QT_BY_INT_GAOSHA_XUELIN"),
        ("SYN_QT_TARGET_INT_3", "文海南路 × 学源街", "intersection", "QT_BY_INT_WENHAINAN_XUEYUAN"),
        ("SYN_QT_TARGET_ROAD_1", "2号大街", "road", "QT_BY_RD_NO2"),
        ("SYN_QT_TARGET_ROAD_2", "学源街", "road", "QT_BY_RD_XUEYUAN"),
    ]
    for event_id, road_name, granularity, location_id in target_specs:
        _save_event({
            "eventId": event_id,
            "eventType": "congestion",
            "eventTypeCn": "拥堵",
            "roadName": road_name,
            "direction": "东向西",
            "avgSpeed": 8,
            "queueLength": 240,
            "duration": 900,
            "vehicleCount": 22,
            "confidence": 0.9,
            "weather": "clear",
            "timePeriod": "morning_peak",
            "isMainRoad": True,
            "nearbySchool": False,
            "nearbyHospital": False,
            "riskScore": 78,
            "riskLevel": "高风险",
            "status": "待派单",
            "createdAt": TARGET_AS_OF,
            "updatedAt": TARGET_AS_OF,
            "rawEvent": {
                "provenance": {
                    "sourceType": "synthetic_validation",
                    "datasetId": DATASET_ID,
                    "datasetVersion": DATASET_VERSION,
                }
            },
            "validation": {
                "locationGranularity": granularity,
                "locationTextSource": "test_target_not_formal_history",
                "expectedCanonicalLocation": {
                    "regionId": REGION_ID,
                    "roadId": location_id if granularity == "road" else None,
                    "intersectionId": location_id if granularity == "intersection" else None,
                },
            },
        })
        EventLocationBindingService(isolated["repo"]).resolve_and_bind(event_id, region_id=REGION_ID)
        context = historical.get_historical_context_for_event(event_id, window_days=365)
        assert context["status"] == "READY"
        assert context["locationGranularity"] == granularity
        assert context["eventCount"] > 0
        assert event_id not in {ref["eventId"] for ref in context["recentEventRefs"]}
        assert context["provenance"]["sourceType"] == "event_records"

    start = SAFE_G3_FROM
    end = "2026-08-01T00:00:00Z"
    intersection_context = historical.get_historical_context(
        region_id=REGION_ID,
        intersection_id="QT_BY_INT_WENZE_NO2",
        start_time=start,
        end_time=end,
    )
    expected_intersection = _expected_aggregate(
        events,
        location_key=("intersection", "QT_BY_INT_WENZE_NO2"),
        start_time=start,
        end_time=end,
    )
    road_context = historical.get_historical_context(
        region_id=REGION_ID,
        road_id="QT_BY_RD_NO2",
        start_time=start,
        end_time=end,
    )
    expected_road = _expected_aggregate(
        events,
        location_key=("road", "QT_BY_RD_NO2"),
        start_time=start,
        end_time=end,
    )

    for context, expected in (
        (intersection_context, expected_intersection),
        (road_context, expected_road),
    ):
        assert context["eventCount"] == expected["eventCount"]
        assert context["eventTypeDistribution"] == expected["eventTypeDistribution"]
        assert context["riskDistribution"] == expected["riskDistribution"]
        assert context["averageDuration"] == expected["averageDuration"]
        assert context["durationSampleCount"] == expected["durationSampleCount"]
        assert context["maxRisk"] == expected["maxRisk"]
        assert context["unclosedCount"] == expected["unclosedCount"]
        assert context["timeOfDayDistribution"] == expected["timeOfDayDistribution"]
        assert [ref["eventId"] for ref in context["recentEventRefs"]] == expected["recentEventRefs"]
        assert len(context["recentEventRefs"]) <= 5
        assert all("rawEvent" not in ref and "fullResult" not in ref for ref in context["recentEventRefs"])


def test_strict_past_cross_region_unbound_and_road_intersection_scope(isolated):
    events = _load_history_pack()["events"]
    _import_events(events)
    _resolve_events(isolated["repo"], events)
    historical = HistoricalTrafficService(isolated["repo"])
    binder = EventLocationBindingService(isolated["repo"])

    same_time = {
        **events[0],
        "eventId": "SYN_QT_TEST_SAME_TIME",
        "roadName": "2号大街",
        "createdAt": "2026-08-15T00:00:00Z",
        "updatedAt": "2026-08-15T00:15:00Z",
        "validation": {
            "locationGranularity": "road",
            "locationTextSource": "test_target_not_formal_history",
            "expectedCanonicalLocation": {"regionId": REGION_ID, "roadId": "QT_BY_RD_NO2", "intersectionId": None},
        },
    }
    future = {
        **same_time,
        "eventId": "SYN_QT_TEST_FUTURE",
        "createdAt": "2026-08-16T00:00:00Z",
        "updatedAt": "2026-08-16T00:15:00Z",
    }
    target = {**same_time, "eventId": "SYN_QT_TEST_TARGET"}
    unbound = {**same_time, "eventId": "SYN_QT_TEST_UNBOUND", "createdAt": "2026-08-14T00:00:00Z"}
    for event in (same_time, future, target, unbound):
        _save_event(event)
    for event_id in ("SYN_QT_TEST_SAME_TIME", "SYN_QT_TEST_FUTURE", "SYN_QT_TEST_TARGET"):
        binder.resolve_and_bind(event_id, region_id=REGION_ID)

    region_b = {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "verificationStatus": "synthetic",
        "region": {"regionId": "TEST_REGION_B", "name": "测试区域B", "city": "测试市", "timezone": "Asia/Shanghai"},
        "roads": [{"roadId": "ROAD_B_NO2", "regionId": "TEST_REGION_B", "name": "2号大街"}],
        "intersections": [],
        "roadRelations": [],
        "pois": [],
    }
    isolated["repo"].import_context_pack(region_b)
    cross_region = {**same_time, "eventId": "SYN_QT_TEST_CROSS_REGION", "createdAt": "2026-08-13T00:00:00Z"}
    _save_event(cross_region)
    binder.resolve_and_bind("SYN_QT_TEST_CROSS_REGION", region_id="TEST_REGION_B")

    context = historical.get_historical_context_for_event("SYN_QT_TEST_TARGET", window_days=30)
    refs = {ref["eventId"] for ref in context["recentEventRefs"]}
    assert "SYN_QT_TEST_SAME_TIME" not in refs
    assert "SYN_QT_TEST_FUTURE" not in refs
    assert "SYN_QT_TEST_TARGET" not in refs
    assert "SYN_QT_TEST_UNBOUND" not in refs
    assert "SYN_QT_TEST_CROSS_REGION" not in refs

    intersection_context = historical.get_historical_context(
        region_id=REGION_ID,
        intersection_id="QT_BY_INT_WENZE_NO2",
        start_time=SAFE_G3_FROM,
        end_time=TARGET_AS_OF,
    )
    road_context = historical.get_historical_context(
        region_id=REGION_ID,
        road_id="QT_BY_RD_NO2",
        start_time=SAFE_G3_FROM,
        end_time="2026-08-15T00:00:00Z",
    )
    intersection_ids = {
        event["eventId"]
        for event in events
        if event["validation"]["expectedCanonicalLocation"]["intersectionId"] == "QT_BY_INT_WENZE_NO2"
    }
    road_ids = {
        event["eventId"]
        for event in events
        if event["validation"]["expectedCanonicalLocation"]["roadId"] == "QT_BY_RD_NO2"
    }
    assert {ref["eventId"] for ref in intersection_context["recentEventRefs"]}.issubset(intersection_ids)
    assert {ref["eventId"] for ref in road_context["recentEventRefs"]}.issubset(road_ids)
    assert intersection_ids.isdisjoint(road_ids)


def test_g1_g2_g3a_grounded_context_smoke_with_synthetic_history(isolated):
    events = _load_history_pack()["events"]
    _import_events(events)
    _resolve_events(isolated["repo"], events)
    _import_g2_knowledge()

    target = {
        **events[0],
        "eventId": "SYN_QT_CONTEXT_TARGET",
        "eventType": "congestion",
        "eventTypeCn": "拥堵",
        "roadName": "文泽路 × 2号大街",
        "duration": 1200,
        "riskLevel": "高风险",
        "riskScore": 88,
        "status": "待派单",
        "createdAt": TARGET_AS_OF,
        "updatedAt": TARGET_AS_OF,
        "validation": {
            "locationGranularity": "intersection",
            "locationTextSource": "test_target_not_formal_history",
            "expectedCanonicalLocation": {
                "regionId": REGION_ID,
                "roadId": None,
                "intersectionId": "QT_BY_INT_WENZE_NO2",
            },
        },
    }
    _save_event(target)
    EventLocationBindingService(isolated["repo"]).resolve_and_bind(target["eventId"], region_id=REGION_ID)

    from backend.grounding.assembler import GroundedEventContextAssembler

    context = GroundedEventContextAssembler(regional_repository=isolated["repo"]).assemble(
        target["eventId"],
        query="早高峰路口排队影响通行需要法规依据",
        knowledge_top_k=5,
        case_top_k=5,
        history_window_days=365,
    ).to_dict()

    assert context["regionalContext"]["status"] == "READY"
    assert context["regionalContext"]["location"]["intersectionId"] == "QT_BY_INT_WENZE_NO2"
    assert context["historicalContext"]["status"] == "READY"
    assert context["historicalContext"]["eventCount"] > 0
    assert context["knowledgeContext"]["status"] == "READY"
    assert context["knowledgeContext"]["evidence"]
    assert context["caseMemoryContext"]["status"] in {"EMPTY", "UNAVAILABLE"}
    assert any(ref["type"] == "historical_traffic" for ref in context["groundingRefs"])
    assert any(ref["type"] == "knowledge_evidence" for ref in context["groundingRefs"])
    encoded = json.dumps(context, ensure_ascii=False)
    assert "rawEvent" not in encoded
    assert "fullResult" not in encoded
    assert "expectedCanonicalLocation" not in encoded
    assert _table_count(isolated["eventDb"], "traffic_case_memories") == 0
    assert isolated["eventDb"].startswith(isolated["tmpRoot"])
    assert isolated["ragDb"].startswith(isolated["tmpRoot"])
    assert isolated["ftsPath"].startswith(isolated["tmpRoot"])
    assert isolated["chromaPath"].startswith(isolated["tmpRoot"])
