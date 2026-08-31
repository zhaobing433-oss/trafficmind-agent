"""Phase21 Wave C canonical historical traffic context tests."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
import backend.regional.api as regional_api
import backend.tools.db_tools as db_tools
from backend.regional.api import router as regional_router
from backend.regional.historical import HistoricalTrafficService
from backend.regional.repository import SQLiteRegionalRepository
from backend.regional.resolver import EventLocationBindingService


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    production_db = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
    test_db = str(tmp_path / "phase21_historical_context.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    monkeypatch.setattr(db_tools, "DB_PATH", test_db)
    db_tools.init_db()
    repo = SQLiteRegionalRepository(db_path=test_db)
    monkeypatch.setattr(regional_api, "_repo", repo)
    return {"repo": repo, "db": test_db, "productionDb": production_db}


@pytest.fixture()
def repo(isolated):
    return isolated["repo"]


@pytest.fixture()
def binder(repo):
    return EventLocationBindingService(repo)


@pytest.fixture()
def historical(repo):
    return HistoricalTrafficService(repo)


@pytest.fixture()
def api_client(isolated):
    app = FastAPI()
    app.include_router(regional_router)
    return TestClient(app)


def _region_a_pack() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_historical_context.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_A",
            "name": "测试区域A",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {
                "roadId": "ROAD_A_PEOPLE",
                "regionId": "TEST_REGION_A",
                "name": "人民路",
            },
            {
                "roadId": "ROAD_A_LIBERATION",
                "regionId": "TEST_REGION_A",
                "name": "解放路",
            },
            {
                "roadId": "ROAD_A_YOUTH",
                "regionId": "TEST_REGION_A",
                "name": "青年路",
            },
            {
                "roadId": "ROAD_A_PEACE",
                "regionId": "TEST_REGION_A",
                "name": "和平路",
            },
        ],
        "intersections": [
            {
                "intersectionId": "INT_A_PEOPLE_LIBERATION",
                "regionId": "TEST_REGION_A",
                "name": "人民路-解放路路口",
                "aliases": ["人民路与解放路交叉口"],
            },
            {
                "intersectionId": "INT_A_YOUTH_PEACE",
                "regionId": "TEST_REGION_A",
                "name": "青年路-和平路路口",
            },
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
                "toEntityId": "INT_A_YOUTH_PEACE",
                "relationType": "connects",
            },
        ],
        "pois": [],
    }


def _region_b_pack() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_B",
            "name": "测试区域B",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {
                "roadId": "ROAD_B_PEOPLE",
                "regionId": "TEST_REGION_B",
                "name": "人民路",
            }
        ],
        "intersections": [],
        "roadRelations": [],
        "pois": [],
    }


def _invalid_timezone_pack() -> dict:
    pack = _region_a_pack()
    pack["region"] = {
        **pack["region"],
        "regionId": "TEST_REGION_BAD_TZ",
        "name": "无效时区测试区",
        "timezone": "Mars/TrafficMind",
    }
    for road in pack["roads"]:
        road["regionId"] = "TEST_REGION_BAD_TZ"
        road["roadId"] = road["roadId"].replace("ROAD_A_", "ROAD_BAD_TZ_")
    for intersection in pack["intersections"]:
        intersection["regionId"] = "TEST_REGION_BAD_TZ"
        intersection["intersectionId"] = intersection["intersectionId"].replace("INT_A_", "INT_BAD_TZ_")
    for relation in pack["roadRelations"]:
        relation["regionId"] = "TEST_REGION_BAD_TZ"
        relation["fromEntityId"] = relation["fromEntityId"].replace("ROAD_A_", "ROAD_BAD_TZ_")
        relation["fromEntityId"] = relation["fromEntityId"].replace("INT_A_", "INT_BAD_TZ_")
        relation["toEntityId"] = relation["toEntityId"].replace("ROAD_A_", "ROAD_BAD_TZ_")
        relation["toEntityId"] = relation["toEntityId"].replace("INT_A_", "INT_BAD_TZ_")
    return pack


def _seed_event(
    event_id: str,
    road_name: str,
    created_at: str,
    *,
    event_type: str = "congestion",
    risk_score: object = 80,
    risk_level: str = "高风险",
    status: str = "待派单",
    duration: object = 600,
) -> None:
    standard_event = {
        "eventId": event_id,
        "eventType": event_type,
        "eventTypeCn": event_type,
        "roadName": road_name,
        "duration": duration,
    }
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": standard_event,
        "riskScore": risk_score,
        "riskLevel": risk_level,
        "status": status,
        "report": "synthetic fixture",
        "analyzedAt": created_at,
    })


def _bind_event(
    binder: EventLocationBindingService,
    event_id: str,
    region_id: str = "TEST_REGION_A",
) -> None:
    result = binder.resolve_and_bind(event_id, region_id=region_id)
    assert result["binding"] is not None


def _set_event_duration(db_path: str, event_id: str, duration: object) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE event_records SET duration = ? WHERE eventId = ?", (duration, event_id))
        conn.commit()
    finally:
        conn.close()


def _table_count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_intersection_history_exact_location_and_aggregations(
    repo,
    binder,
    historical,
    isolated,
):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_HIST_1", "人民路-解放路路口", "2026-01-20 08:00:00")
    _seed_event(
        "E_HIST_2",
        "人民路与解放路交叉口",
        "2026-01-25 19:00:00",
        event_type="accident",
        risk_score=95,
        risk_level="重大风险",
        status="已处置",
        duration=1200,
    )
    _seed_event("E_OTHER_INT", "青年路-和平路路口", "2026-01-25 09:00:00")
    _seed_event("E_FUTURE", "人民路-解放路路口", "2026-02-01 08:00:00")
    _seed_event("E_TARGET_INT", "人民路-解放路路口", "2026-01-30 10:00:00")
    for event_id in ("E_HIST_1", "E_HIST_2", "E_OTHER_INT", "E_FUTURE", "E_TARGET_INT"):
        _bind_event(binder, event_id)
    _set_event_duration(isolated["db"], "E_HIST_2", None)

    context = historical.get_historical_context_for_event("E_TARGET_INT", window_days=30)

    assert context["status"] == "READY"
    assert context["locationGranularity"] == "intersection"
    assert context["intersectionId"] == "INT_A_PEOPLE_LIBERATION"
    assert context["eventCount"] == 2
    assert context["eventTypeDistribution"] == {"accident": 1, "congestion": 1}
    assert context["riskDistribution"] == {"重大风险": 1, "高风险": 1}
    assert context["maxRisk"] == 95.0
    assert context["averageDuration"] == 600.0
    assert context["durationSampleCount"] == 1
    assert context["unclosedCount"] == 1
    assert context["timeOfDayDistribution"]["06-12"] == 1
    assert context["timeOfDayDistribution"]["18-24"] == 1
    assert set(context["connectedRoadIds"]) == {"ROAD_A_LIBERATION", "ROAD_A_PEOPLE"}
    assert {item["eventId"] for item in context["recentEventRefs"]} == {"E_HIST_1", "E_HIST_2"}


def test_holdout_history_excludes_current_and_future_events(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_T_MINUS_10D", "人民路", "2026-01-20 10:00:00")
    _seed_event("E_T_MINUS_3D", "人民路", "2026-01-27 10:00:00")
    _seed_event("E_HOLDOUT", "人民路", "2026-01-30 10:00:00")
    _seed_event("E_T_PLUS_1D", "人民路", "2026-01-31 10:00:00")
    _seed_event("E_T_PLUS_5D", "人民路", "2026-02-04 10:00:00")
    for event_id in (
        "E_T_MINUS_10D",
        "E_T_MINUS_3D",
        "E_HOLDOUT",
        "E_T_PLUS_1D",
        "E_T_PLUS_5D",
    ):
        _bind_event(binder, event_id)

    seven_day = historical.get_historical_context_for_event("E_HOLDOUT", window_days=7)
    ninety_day = historical.get_historical_context_for_event("E_HOLDOUT", window_days=90)

    assert [item["eventId"] for item in seven_day["recentEventRefs"]] == ["E_T_MINUS_3D"]
    assert {item["eventId"] for item in ninety_day["recentEventRefs"]} == {
        "E_T_MINUS_10D",
        "E_T_MINUS_3D",
    }
    assert "E_HOLDOUT" not in {item["eventId"] for item in ninety_day["recentEventRefs"]}
    assert "E_T_PLUS_1D" not in {item["eventId"] for item in ninety_day["recentEventRefs"]}
    assert "E_T_PLUS_5D" not in {item["eventId"] for item in ninety_day["recentEventRefs"]}


def test_window_start_inclusive_and_asof_exclusive(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_WINDOW_START", "人民路", "2026-01-01 10:00:00")
    _seed_event("E_WINDOW_BEFORE", "人民路", "2026-01-01 09:59:59")
    _seed_event("E_WINDOW_SAME_TIME", "人民路", "2026-01-31 10:00:00")
    _seed_event("E_WINDOW_TARGET", "人民路", "2026-01-31 10:00:00")
    for event_id in ("E_WINDOW_START", "E_WINDOW_BEFORE", "E_WINDOW_SAME_TIME", "E_WINDOW_TARGET"):
        _bind_event(binder, event_id)

    context = historical.get_historical_context_for_event("E_WINDOW_TARGET", window_days=30)

    assert [item["eventId"] for item in context["recentEventRefs"]] == ["E_WINDOW_START"]


def test_road_history_exact_and_same_name_cross_region_isolated(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    repo.import_context_pack(_region_b_pack())
    _seed_event("E_A_ROAD_HISTORY", "人民路", "2026-01-20 10:00:00")
    _seed_event("E_A_OTHER_ROAD", "解放路", "2026-01-21 10:00:00")
    _seed_event("E_A_CONNECTED_INTERSECTION", "人民路-解放路路口", "2026-01-22 10:00:00")
    _seed_event("E_B_SAME_NAME", "人民路", "2026-01-22 10:00:00")
    _seed_event("E_A_ROAD_TARGET", "人民路", "2026-01-30 10:00:00")
    _bind_event(binder, "E_A_ROAD_HISTORY", "TEST_REGION_A")
    _bind_event(binder, "E_A_OTHER_ROAD", "TEST_REGION_A")
    _bind_event(binder, "E_A_CONNECTED_INTERSECTION", "TEST_REGION_A")
    _bind_event(binder, "E_B_SAME_NAME", "TEST_REGION_B")
    _bind_event(binder, "E_A_ROAD_TARGET", "TEST_REGION_A")

    context = historical.get_historical_context_for_event("E_A_ROAD_TARGET", window_days=30)

    assert context["locationGranularity"] == "road"
    assert context["roadId"] == "ROAD_A_PEOPLE"
    assert context["eventCount"] == 1
    assert [item["eventId"] for item in context["recentEventRefs"]] == ["E_A_ROAD_HISTORY"]


def test_historical_context_query_does_not_write_bindings(repo, binder, historical, isolated):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_READONLY_HISTORY", "人民路", "2026-01-20 10:00:00")
    _seed_event("E_READONLY_TARGET", "人民路", "2026-01-30 10:00:00")
    _bind_event(binder, "E_READONLY_HISTORY")
    _bind_event(binder, "E_READONLY_TARGET")
    before = _table_count(isolated["db"], "event_location_bindings")

    context = historical.get_historical_context_for_event("E_READONLY_TARGET", window_days=30)

    assert context["status"] == "READY"
    assert _table_count(isolated["db"], "event_location_bindings") == before


def test_direct_canonical_history_query_supports_window_and_exclusion(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_DIRECT_1", "人民路", "2026-01-20 10:00:00")
    _seed_event("E_DIRECT_EXCLUDED", "人民路", "2026-01-21 10:00:00")
    _seed_event("E_DIRECT_OUTSIDE", "人民路", "2026-02-01 10:00:00")
    for event_id in ("E_DIRECT_1", "E_DIRECT_EXCLUDED", "E_DIRECT_OUTSIDE"):
        _bind_event(binder, event_id)

    context = historical.get_historical_context(
        region_id="TEST_REGION_A",
        road_id="ROAD_A_PEOPLE",
        start_time="2026-01-01 00:00:00",
        end_time="2026-01-30 00:00:00",
        exclude_event_id="E_DIRECT_EXCLUDED",
    )

    assert context["status"] == "READY"
    assert context["eventCount"] == 1
    assert [item["eventId"] for item in context["recentEventRefs"]] == ["E_DIRECT_1"]


def test_unbound_and_superseded_events_do_not_enter_canonical_history(
    repo,
    binder,
    historical,
):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_ACTIVE_PEOPLE", "人民路", "2026-01-18 10:00:00")
    _seed_event("E_UNBOUND_LEGACY", "人民路", "2026-01-19 10:00:00")
    _seed_event("E_CHANGED", "人民路", "2026-01-20 10:00:00")
    _seed_event("E_TARGET_PEOPLE", "人民路", "2026-01-30 10:00:00")
    _bind_event(binder, "E_ACTIVE_PEOPLE")
    _bind_event(binder, "E_CHANGED")
    _seed_event("E_CHANGED", "解放路", "2026-01-20 10:00:00")
    changed = binder.resolve_and_bind("E_CHANGED", region_id="TEST_REGION_A", re_resolve=True)
    assert changed["binding"]["roadId"] == "ROAD_A_LIBERATION"
    _bind_event(binder, "E_TARGET_PEOPLE")

    context = historical.get_historical_context_for_event("E_TARGET_PEOPLE", window_days=30)

    assert context["eventCount"] == 1
    assert [item["eventId"] for item in context["recentEventRefs"]] == ["E_ACTIVE_PEOPLE"]


def test_zero_history_is_ready_but_unbound_event_is_unavailable(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_ZERO_TARGET", "人民路", "2026-01-30 10:00:00")
    _seed_event("E_UNBOUND_TARGET", "人民路", "2026-01-30 10:00:00")
    _bind_event(binder, "E_ZERO_TARGET")

    ready = historical.get_historical_context_for_event("E_ZERO_TARGET", window_days=30)
    unavailable = historical.get_historical_context_for_event("E_UNBOUND_TARGET", window_days=30)

    assert ready["status"] == "READY"
    assert ready["eventCount"] == 0
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["reason"] == "LOCATION_NOT_RESOLVED"
    assert unavailable["eventCount"] == 0


def test_recent_event_refs_bounded_stable_and_no_full_raw_payload(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    for idx in range(6):
        _seed_event(f"E_RECENT_{idx}", "人民路", f"2026-01-2{idx} 10:00:00")
        _bind_event(binder, f"E_RECENT_{idx}")
    _seed_event("E_RECENT_TARGET", "人民路", "2026-01-30 10:00:00")
    _bind_event(binder, "E_RECENT_TARGET")

    context = historical.get_historical_context_for_event("E_RECENT_TARGET", window_days=30)

    refs = context["recentEventRefs"]
    assert len(refs) == 5
    assert [item["eventId"] for item in refs] == [
        "E_RECENT_5",
        "E_RECENT_4",
        "E_RECENT_3",
        "E_RECENT_2",
        "E_RECENT_1",
    ]
    assert all("rawEvent" not in item and "fullResult" not in item for item in refs)


def test_time_of_day_uses_region_timezone(repo, binder, historical):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_UTC_NIGHT", "人民路", "2026-01-01T23:30:00+00:00")
    _seed_event("E_TZ_TARGET", "人民路", "2026-01-02T10:00:00+08:00")
    _bind_event(binder, "E_UTC_NIGHT")
    _bind_event(binder, "E_TZ_TARGET")

    context = historical.get_historical_context_for_event("E_TZ_TARGET", window_days=7)

    assert context["eventCount"] == 1
    assert context["timeOfDayDistribution"]["06-12"] == 1


def test_invalid_region_timezone_is_degraded_not_silent_utc(repo, binder, historical):
    repo.import_context_pack(_invalid_timezone_pack())
    _seed_event("E_BAD_TZ_TARGET", "人民路", "2026-01-30 10:00:00")
    _bind_event(binder, "E_BAD_TZ_TARGET", "TEST_REGION_BAD_TZ")

    context = historical.get_historical_context_for_event("E_BAD_TZ_TARGET", window_days=30)

    assert context["status"] == "UNAVAILABLE"
    assert context["reason"] == "INVALID_REGION_TIMEZONE"


def test_history_api_missing_event_404_and_unbound_event_200_unavailable(
    api_client,
    repo,
):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_API_UNBOUND", "人民路", "2026-01-30 10:00:00")

    missing = api_client.get("/regional/events/E_DOES_NOT_EXIST/history")
    unbound = api_client.get("/regional/events/E_API_UNBOUND/history?windowDays=30")

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "event_not_found"
    assert unbound.status_code == 200
    assert unbound.json()["status"] == "UNAVAILABLE"
    assert unbound.json()["reason"] == "LOCATION_NOT_RESOLVED"


def test_production_db_untouched_by_historical_context_tests(isolated):
    assert isolated["db"] != isolated["productionDb"]
    assert not isolated["db"].endswith("backend/data/trafficmind.db")
