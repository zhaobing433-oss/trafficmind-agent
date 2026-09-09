"""Phase22 Qiantang Pilot demo reality and isolation contracts."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
REGION_DIR = BACKEND_DIR / "data" / "pilot_regions" / "qt_by_xiasha_pilot_001"
PUBLIC_DIR = BACKEND_DIR / "data" / "pilot_history_public" / "qt_by_xiasha_pilot_001"
HOLDOUT_DIR = BACKEND_DIR / "data" / "pilot_holdout" / "qt_by_xiasha_pilot_001"
DEMO_DIR = BACKEND_DIR / "data" / "pilot_demo" / "qt_by_xiasha_pilot_001"
LAUNCHER = REPO_ROOT / "scripts" / "start-qiantang-demo.sh"
RUNTIME_DIR = DEMO_DIR / "runtime_test"
REGION_ID = "QT_BY_XIASHA_PILOT_001"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_public_history_pack_is_source_grounded_canonical_and_pii_minimized():
    package = _load(PUBLIC_DIR / "package.json")
    events = _load(PUBLIC_DIR / "events.json")["events"]
    sources = {row["sourceId"]: row for row in _load(PUBLIC_DIR / "source_register.json")["sources"]}
    intersections = {row["intersectionId"] for row in _load(REGION_DIR / "intersections.json")}
    roads = {row["roadId"] for row in _load(REGION_DIR / "roads.json")}

    assert package["datasetReality"] == "real_public_reported_incident_history"
    assert len(events) == 4
    assert sum(row["canonicalBinding"]["bindingType"] == "exact_intersection" for row in events) == 2
    assert sum(row["canonicalBinding"]["bindingType"] == "road_bound" for row in events) == 2
    assert all(row["sourceId"] in sources for row in events)
    assert all(sources[row["sourceId"]]["sourceTier"] in {"A", "B", "C"} for row in events)
    assert all(sources[row["sourceId"]]["sourceUri"].startswith("https://") for row in events)
    assert all(row["canonicalBinding"]["regionId"] == REGION_ID for row in events)
    assert all(
        row["canonicalBinding"].get("intersectionId") in intersections
        or row["canonicalBinding"].get("roadId") in roads
        for row in events
    )

    forbidden_fact_keys = {
        "personName", "name", "plate", "plateNumber", "identityNumber", "idCard",
        "hospital", "medicalAmount", "insurance", "address", "compensationAmount",
    }
    forbidden_source_person_tokens = {"张某某", "周某某", "王玉芳", "丁松寿", "姚德青", "王波", "ZHANABAYEV"}
    assert not ({key for key, _ in _walk(events)} & forbidden_fact_keys)
    serialized = json.dumps(events, ensure_ascii=False)
    assert all(token not in serialized for token in forbidden_source_person_tokens)
    assert all(key not in row for row in events for key in ("riskScore", "riskLevel", "plan", "workflow", "approval"))


def test_excluded_candidates_are_not_promoted_or_used_to_expand_g1():
    excluded = _load(PUBLIC_DIR / "excluded_candidates.json")["candidates"]
    events = _load(PUBLIC_DIR / "events.json")["events"]
    assert len(excluded) == 7
    reasons = {row["reason"] for row in excluded}
    assert {"SOURCE_NOT_VERIFIED", "OUTSIDE_CURRENT_PILOT", "AGGREGATE_NOT_SINGLE_INCIDENT"} <= reasons
    accepted = json.dumps(events, ensure_ascii=False)
    assert all(name not in accepted for name in ("云涛南路", "华景街", "德胜东路"))


def test_demo_manifest_reuses_holdout_and_freezes_replay_reality():
    manifest = _load(DEMO_DIR / "demo_manifest.json")
    holdout = {row["eventId"]: row for row in _load(HOLDOUT_DIR / "holdout_events.json")["events"]}
    current = [holdout[event_id] for event_id in manifest["currentEventIds"]]
    assert manifest["approvalPolicy"]["frozenBeforeExecution"] is True
    assert manifest["approvalPolicy"]["visibleToAgent"] is False
    assert [row["decision"] for row in manifest["publicReplay"]] == ["approve", "reject"]
    assert len(current) == 8
    assert len({row["eventType"] for row in current}) == 6
    assert len({
        row["validation"]["expectedCanonicalLocation"].get("intersectionId")
        or row["validation"]["expectedCanonicalLocation"].get("roadId")
        for row in current
    }) == 8
    assert all(row["validation"]["expectedCanonicalLocation"]["regionId"] == REGION_ID for row in current)


def test_demo_environment_is_explicit_and_never_the_production_default():
    from backend.tools.qiantang_demo_runtime import demo_environment, ensure_isolated_runtime

    values = demo_environment(RUNTIME_DIR)
    assert values["QIANTANG_DEMO"] == "1"
    assert values["RAG_EMBEDDING_MODEL"] == "Qwen/Qwen3-Embedding-0.6B"
    assert values["RAG_ALLOW_HASH_FALLBACK"] == "false"
    assert Path(values["TRAFFICMIND_DB_PATH"]).resolve() != (BACKEND_DIR / "data" / "trafficmind.db").resolve()
    assert ensure_isolated_runtime(RUNTIME_DIR) == RUNTIME_DIR.resolve()
    with pytest.raises(ValueError):
        ensure_isolated_runtime(REPO_ROOT / "outside-demo")


def test_history_provenance_fields_are_extracted_without_exposing_raw_payload():
    from backend.tools import db_tools

    original_path = db_tools.DB_PATH
    database = RUNTIME_DIR.parent / "history_contract_test.db"
    try:
        db_tools.DB_PATH = str(database)
        db_tools.init_db()
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO event_records (
                    eventId, eventType, eventTypeCn, roadName, riskScore, riskLevel,
                    status, rawEvent, fullResult, createdAt, updatedAt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "HISTORY_PROVENANCE_TEST", "accident", "事故", "学林街", 0, "未评估",
                    "历史记录", json.dumps({"provenance": {
                        "sourceType": "real_public_reported_incident",
                        "datasetReality": "real_public_reported_incident_history",
                    }}), "{}", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z",
                ),
            )
            connection.commit()
        row = db_tools.get_history(limit=1)[0]
        assert row["sourceType"] == "real_public_reported_incident"
        assert row["datasetReality"] == "real_public_reported_incident_history"
        assert "rawEvent" not in row
    finally:
        db_tools.DB_PATH = original_path
        database.unlink(missing_ok=True)


def test_one_command_launcher_locks_demo_ports_stores_and_frontend_target():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert LAUNCHER.stat().st_mode & 0o111
    assert "backend.tools.materialize_qiantang_demo" in source
    assert "backend.tools.run_qiantang_demo" in source
    assert 'VITE_RUNTIME_PROFILE="qiantang-demo"' in source
    assert 'VITE_PROXY_TARGET="$BACKEND_URL"' in source
    assert "--strictPort" in source
    assert "QIANTANG_DEMO_BACKEND_PORT:-8011" in source
    assert "QIANTANG_DEMO_FRONTEND_PORT:-5174" in source
    assert "trap cleanup" in source
    assert "killall" not in source
    assert "Demo API verification failed" in source
    assert "runtime_matches_snapshot" in source
    assert '_database_snapshot(root / "trafficmind_demo.db")' in source


@pytest.mark.skipif(
    os.getenv("RUN_QIANTANG_DEMO_MATERIALIZATION") != "1",
    reason="set RUN_QIANTANG_DEMO_MATERIALIZATION=1 for the real-Qwen isolated runtime test",
)
def test_fresh_demo_materialization_is_idempotent_and_truthful():
    try:
        first = subprocess.run(
            [sys.executable, "-m", "backend.tools.materialize_qiantang_demo", "--runtime-dir", str(RUNTIME_DIR), "--reset"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
        assert first.returncode == 0
        first_report = _load(RUNTIME_DIR / "materialization_report.json")
        second = subprocess.run(
            [sys.executable, "-m", "backend.tools.materialize_qiantang_demo", "--runtime-dir", str(RUNTIME_DIR)],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert second.returncode == 0
        second_report = _load(RUNTIME_DIR / "materialization_report.json")

        assert first_report["businessSnapshot"] == second_report["businessSnapshot"]
        assert second_report["embedding"] == {
            "model": "Qwen/Qwen3-Embedding-0.6B",
            "resolvedModel": "Qwen/Qwen3-Embedding-0.6B",
            "dimension": 1024,
            "degraded": False,
        }
        assert second_report["legacyTestEventCount"] == 0
        assert second_report["currentEventCount"] == 8
        assert second_report["publicReplayCaseCount"] == 2
        assert second_report["publicReplayStatusCounts"] == {"completed": 1, "rejected": 1}
        assert second_report["syntheticClosureCaseCount"] == 8
        assert second_report["memoryRetrieval"]["publicReplayRetrievable"] is True
        assert second_report["memoryRetrieval"]["syntheticClosureRetrievable"] is True
        assert second_report["memoryRetrieval"]["wrongRegionCount"] == 0
        assert second_report["memoryRetrieval"]["futureLeakageCount"] == 0

        database = RUNTIME_DIR / "trafficmind_demo.db"
        with sqlite3.connect(database) as connection:
            public_rows = connection.execute(
                "SELECT rawEvent, fullResult FROM event_records WHERE eventId LIKE 'PUB_QT_HIST_%'"
            ).fetchall()
            cases = connection.execute(
                "SELECT source_type, final_status, provenance_json, workflow_outcome_json FROM traffic_case_memories"
            ).fetchall()
        assert len(public_rows) == 4
        assert all("real_public_reported_incident" in row[0] for row in public_rows)
        public_cases = [row for row in cases if row[0] == "public_incident_replay_system_closure"]
        assert {row[1] for row in public_cases} == {"completed", "rejected"}
        assert all(json.loads(row[2])["sourceEventReality"] == "real_public_reported_incident" for row in public_cases)
        assert all(
            json.loads(row[3])["businessOutcome"]["status"] == "unknown_without_external_evidence"
            for row in public_cases
        )
    finally:
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
