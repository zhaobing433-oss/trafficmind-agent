"""Phase21 Wave B location resolver and event binding tests.

All tests use isolated synthetic region/event data in a temporary SQLite DB.
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

import backend.config as cfg
import backend.regional.api as regional_api
import backend.tools.db_tools as db_tools
from backend.regional.api import router as regional_router
from backend.regional.repository import SQLiteRegionalRepository
from backend.regional.resolver import EventLocationBindingService


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    production_db = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
    test_db = str(tmp_path / "phase21_location_binding.db")
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
def service(repo):
    return EventLocationBindingService(repo)


@pytest.fixture()
def api_client(isolated):
    app = FastAPI()
    app.include_router(regional_router)
    return TestClient(app)


def _region_a_pack() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_location_binding.py",
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
                "aliases": ["人民路南段"],
            },
            {
                "roadId": "ROAD_A_LIBERATION",
                "regionId": "TEST_REGION_A",
                "name": "解放路",
            },
        ],
        "intersections": [
            {
                "intersectionId": "INT_A_PEOPLE_LIBERATION",
                "regionId": "TEST_REGION_A",
                "name": "人民路-解放路路口",
                "aliases": ["人民路与解放路交叉口"],
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
        ],
        "pois": [
            {
                "poiId": "POI_A_SCHOOL",
                "regionId": "TEST_REGION_A",
                "name": "测试小学",
                "type": "school",
                "intersectionId": "INT_A_PEOPLE_LIBERATION",
            },
            {
                "poiId": "POI_A_HOSPITAL",
                "regionId": "TEST_REGION_A",
                "name": "测试医院",
                "type": "hospital",
                "roadId": "ROAD_A_PEOPLE",
            },
            {
                "poiId": "POI_A_COORD_ONLY",
                "regionId": "TEST_REGION_A",
                "name": "坐标点位",
                "type": "other_critical",
                "latitude": 30.1,
                "longitude": 120.2,
            },
        ],
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


def _seed_event(event_id: str, road_name: str, *, direction: str = "东向西") -> None:
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": "congestion",
            "eventTypeCn": "拥堵",
            "roadName": road_name,
            "direction": direction,
            "avgSpeed": 12,
            "queueLength": 80,
            "duration": 600,
            "nearbySchool": True,
            "nearbyHospital": False,
        },
        "riskScore": 80,
        "riskLevel": "高风险",
        "status": "待派单",
        "report": "synthetic fixture",
    })


def _binding_rows(db_path: str, event_id: str) -> list[tuple[str, str, str | None, str | None]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            """
            SELECT status, region_id, road_id, intersection_id
            FROM event_location_bindings
            WHERE event_id = ?
            ORDER BY created_at, binding_id
            """,
            (event_id,),
        ).fetchall()
    finally:
        conn.close()


def _table_count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_location_preview_does_not_write_bindings(service, repo, isolated):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_PREVIEW_ONLY", "人民路")
    before = _table_count(isolated["db"], "event_location_bindings")

    result = service.preview("E_LOC_PREVIEW_ONLY", region_id="TEST_REGION_A")

    assert result["status"] == "resolved"
    assert _table_count(isolated["db"], "event_location_bindings") == before
    assert repo.get_active_event_location_binding("E_LOC_PREVIEW_ONLY") is None


def test_exact_intersection_alias_resolves(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_001", "人民路与解放路交叉口")
    result = service.preview("E_LOC_001", region_id="TEST_REGION_A")
    assert result["status"] == "resolved"
    assert result["resolutionMethod"] == "EXACT_INTERSECTION_ALIAS"
    assert result["intersectionId"] == "INT_A_PEOPLE_LIBERATION"


def test_normalized_intersection_alias_resolves_exact(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_002", "人民路/解放路路口")
    result = service.preview("E_LOC_002", region_id="TEST_REGION_A")
    assert result["status"] == "resolved"
    assert result["resolutionMethod"] == "NORMALIZED_NAME_MATCH"
    assert result["intersectionId"] == "INT_A_PEOPLE_LIBERATION"


def test_intersection_text_does_not_bind_substring_road(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_003", "人民路-解放路路口")
    result = service.preview("E_LOC_003", region_id="TEST_REGION_A")
    assert result["status"] == "resolved"
    assert result["intersectionId"] == "INT_A_PEOPLE_LIBERATION"
    assert result["roadId"] is None


def test_exact_road_alias_resolves(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_004", "人民路南段")
    result = service.preview("E_LOC_004", region_id="TEST_REGION_A")
    assert result["status"] == "resolved"
    assert result["resolutionMethod"] == "EXACT_ROAD_ALIAS"
    assert result["roadId"] == "ROAD_A_PEOPLE"


def test_normalized_road_alias_resolves(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_005", " 人 民 路 ")
    result = service.preview("E_LOC_005", region_id="TEST_REGION_A")
    assert result["status"] == "resolved"
    assert result["resolutionMethod"] == "NORMALIZED_NAME_MATCH"
    assert result["roadId"] == "ROAD_A_PEOPLE"


def test_unknown_name_unresolved(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_006", "不存在道路")
    result = service.preview("E_LOC_006", region_id="TEST_REGION_A")
    assert result["status"] == "unresolved"
    assert result["regionId"] is None
    assert result["roadId"] is None
    assert result["intersectionId"] is None


def test_same_road_name_across_regions_without_scope_ambiguous(service, repo):
    repo.import_context_pack(_region_a_pack())
    repo.import_context_pack(_region_b_pack())
    _seed_event("E_LOC_007", "人民路")
    result = service.preview("E_LOC_007")
    assert result["status"] == "ambiguous"
    assert {c["regionId"] for c in result["candidates"]} == {"TEST_REGION_A", "TEST_REGION_B"}


def test_region_scoped_lookup_resolves_correct_region(service, repo):
    repo.import_context_pack(_region_a_pack())
    repo.import_context_pack(_region_b_pack())
    _seed_event("E_LOC_008", "人民路")
    result = service.preview("E_LOC_008", region_id="TEST_REGION_B")
    assert result["status"] == "resolved"
    assert result["regionId"] == "TEST_REGION_B"
    assert result["roadId"] == "ROAD_B_PEOPLE"


def test_ambiguous_result_does_not_create_active_fake_binding(service, repo):
    repo.import_context_pack(_region_a_pack())
    repo.import_context_pack(_region_b_pack())
    _seed_event("E_LOC_009", "人民路")
    result = service.resolve_and_bind("E_LOC_009")
    assert result["binding"] is None
    assert result["resolution"]["status"] == "ambiguous"
    assert repo.get_active_event_location_binding("E_LOC_009") is None


def test_unresolved_does_not_fake_canonical_ids(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_010", "未知来源事件")
    result = service.resolve_and_bind("E_LOC_010", region_id="TEST_REGION_A")
    assert result["binding"] is None
    assert result["resolution"]["status"] == "unresolved"
    assert result["resolution"]["regionId"] is None
    assert result["resolution"]["roadId"] is None
    assert result["resolution"]["intersectionId"] is None


def test_resolved_event_location_binding_persisted(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_011", "人民路-解放路路口")
    result = service.resolve_and_bind("E_LOC_011", region_id="TEST_REGION_A")
    assert result["binding"]["eventId"] == "E_LOC_011"
    assert result["binding"]["status"] == "resolved"
    assert result["binding"]["intersectionId"] == "INT_A_PEOPLE_LIBERATION"


def test_binding_event_id_is_authoritative(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_012", "人民路")
    result = service.resolve_and_bind(
        "E_LOC_012",
        region_id="TEST_REGION_A",
        client_event={"eventId": "E_LOC_012", "roadName": "解放路", "roadId": "ROAD_FAKE"},
    )
    assert result["binding"]["eventId"] == "E_LOC_012"
    assert result["binding"]["roadId"] == "ROAD_A_PEOPLE"


def test_binding_location_belongs_same_region(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_013", "人民路")
    result = service.resolve_and_bind("E_LOC_013", region_id="TEST_REGION_A")
    binding = result["binding"]
    road = repo.get_road(binding["roadId"])
    assert road["regionId"] == binding["regionId"]


def test_repeat_resolve_same_event_same_result_idempotent(service, repo, isolated):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_014", "人民路")
    first = service.resolve_and_bind("E_LOC_014", region_id="TEST_REGION_A")
    second = service.resolve_and_bind("E_LOC_014", region_id="TEST_REGION_A")
    assert first["binding"]["bindingId"] == second["binding"]["bindingId"]
    assert second["binding"]["idempotent"] is True
    assert len(_binding_rows(isolated["db"], "E_LOC_014")) == 1


def test_explicit_reresolution_same_result_no_duplicate_active(service, repo, isolated):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_015", "人民路")
    first = service.resolve_and_bind("E_LOC_015", region_id="TEST_REGION_A")
    second = service.resolve_and_bind("E_LOC_015", region_id="TEST_REGION_A", re_resolve=True)
    assert first["binding"]["bindingId"] == second["binding"]["bindingId"]
    rows = _binding_rows(isolated["db"], "E_LOC_015")
    assert len(rows) == 1
    assert rows[0][0] == "resolved"


def test_explicit_reresolution_changed_location_supersedes_previous(service, repo, isolated):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_016", "人民路")
    first = service.resolve_and_bind("E_LOC_016", region_id="TEST_REGION_A")
    _seed_event("E_LOC_016", "解放路")
    changed = service.resolve_and_bind("E_LOC_016", region_id="TEST_REGION_A", re_resolve=True)
    assert changed["binding"]["bindingId"] != first["binding"]["bindingId"]
    assert changed["binding"]["roadId"] == "ROAD_A_LIBERATION"
    rows = _binding_rows(isolated["db"], "E_LOC_016")
    assert [row[0] for row in rows] == ["superseded", "resolved"]


def test_changed_resolution_without_explicit_reresolve_fails(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_017", "人民路")
    service.resolve_and_bind("E_LOC_017", region_id="TEST_REGION_A")
    _seed_event("E_LOC_017", "解放路")
    with pytest.raises(Exception) as exc:
        service.resolve_and_bind("E_LOC_017", region_id="TEST_REGION_A")
    assert "regional validation failed" in str(exc.value)
    assert repo.get_active_event_location_binding("E_LOC_017")["roadId"] == "ROAD_A_PEOPLE"


def test_event_missing_api_returns_404(api_client, repo):
    repo.import_context_pack(_region_a_pack())
    response = api_client.post(
        "/regional/events/E_MISSING/location/preview",
        json={"regionId": "TEST_REGION_A"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "event_not_found"


def test_client_supplied_fake_road_id_cannot_override_authoritative_resolver(api_client, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_018", "人民路")
    response = api_client.post(
        "/regional/events/E_LOC_018/location/resolve",
        json={
            "regionId": "TEST_REGION_A",
            "event": {"eventId": "E_LOC_018", "roadName": "解放路", "roadId": "ROAD_FAKE"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["binding"]["roadId"] == "ROAD_A_PEOPLE"


def test_binding_query_exact_event_id(api_client, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_019", "人民路")
    api_client.post("/regional/events/E_LOC_019/location/resolve", json={"regionId": "TEST_REGION_A"})
    response = api_client.get("/regional/events/E_LOC_019/location-binding")
    assert response.status_code == 200
    assert response.json()["binding"]["eventId"] == "E_LOC_019"
    missing = api_client.get("/regional/events/E_LOC_019_suffix/location-binding")
    assert missing.status_code == 404


def test_connected_roads_returned_from_road_relations(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_020", "人民路-解放路路口")
    result = service.resolve_and_bind("E_LOC_020", region_id="TEST_REGION_A")
    connected = result["locationContext"]["connectedRoads"]
    assert {road["roadId"] for road in connected} == {"ROAD_A_PEOPLE", "ROAD_A_LIBERATION"}


def test_poi_nearby_only_through_explicit_road_or_intersection_links(service, repo):
    repo.import_context_pack(_region_a_pack())
    _seed_event("E_LOC_021", "人民路-解放路路口")
    result = service.resolve_and_bind("E_LOC_021", region_id="TEST_REGION_A")
    poi_ids = {poi["poiId"] for poi in result["locationContext"]["nearbyPois"]}
    assert "POI_A_SCHOOL" in poi_ids
    assert "POI_A_COORD_ONLY" not in poi_ids


def test_production_db_untouched_by_tests(isolated):
    assert isolated["db"] != isolated["productionDb"]
    assert not isolated["db"].endswith("backend/data/trafficmind.db")
