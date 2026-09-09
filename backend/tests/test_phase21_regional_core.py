"""Phase21 Wave A regional core tests.

All tests use isolated temporary SQLite databases. They must not touch
backend/data/trafficmind.db or create pilot production content.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.regional.api import router as regional_router
import backend.regional.api as regional_api
from backend.regional.importer import load_context_pack_from_directory
from backend.regional.normalization import normalize_alias
from backend.regional.repository import (
    RegionalValidationError,
    SQLiteRegionalRepository,
    init_regional_tables,
)


@pytest.fixture()
def repo(tmp_path):
    db_path = str(tmp_path / "phase21_regional_core.db")
    assert db_path != cfg.DB_PATH
    return SQLiteRegionalRepository(db_path=db_path)


@pytest.fixture()
def api_client(repo, monkeypatch):
    monkeypatch.setattr(regional_api, "_repo", repo)
    app = FastAPI()
    app.include_router(regional_router)
    return TestClient(app)


def _base_pack() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_regional_core.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_001",
            "name": "测试试点区域",
            "city": "测试市",
            "district": "测试区",
            "timezone": "Asia/Shanghai",
            "status": "active",
            "metadata": {"purpose": "unit-test"},
        },
        "roads": [
            {
                "roadId": "ROAD_TEST_A",
                "regionId": "TEST_REGION_001",
                "name": "人民路",
                "aliases": ["人民 路", "人民路"],
                "roadType": "arterial",
                "directionMode": "two_way",
                "lengthMeters": 1200,
                "status": "active",
            },
            {
                "roadId": "ROAD_TEST_B",
                "regionId": "TEST_REGION_001",
                "name": "解放路",
                "aliases": ["解放 路"],
                "status": "active",
            },
        ],
        "intersections": [
            {
                "intersectionId": "INT_TEST_001",
                "regionId": "TEST_REGION_001",
                "name": "人民路-解放路路口",
                "aliases": ["人民路与解放路交叉口", "人民路/解放路路口"],
                "latitude": 31.23,
                "longitude": 121.47,
                "intersectionType": "crossroad",
                "importance": "high",
                "status": "active",
            }
        ],
        "roadRelations": [
            {
                "relationId": "REL_TEST_CONNECT_A",
                "regionId": "TEST_REGION_001",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_TEST_A",
                "toEntityType": "intersection",
                "toEntityId": "INT_TEST_001",
                "relationType": "connects",
                "status": "active",
            },
            {
                "relationId": "REL_TEST_CONNECT_B",
                "regionId": "TEST_REGION_001",
                "fromEntityType": "intersection",
                "fromEntityId": "INT_TEST_001",
                "toEntityType": "road",
                "toEntityId": "ROAD_TEST_B",
                "relationType": "connects",
                "status": "active",
            },
            {
                "relationId": "REL_TEST_ADJACENT",
                "regionId": "TEST_REGION_001",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_TEST_A",
                "toEntityType": "road",
                "toEntityId": "ROAD_TEST_B",
                "relationType": "adjacent",
                "distanceMeters": 80,
                "status": "active",
            },
            {
                "relationId": "REL_TEST_UPSTREAM",
                "regionId": "TEST_REGION_001",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_TEST_B",
                "toEntityType": "road",
                "toEntityId": "ROAD_TEST_A",
                "relationType": "upstream",
                "status": "active",
            },
            {
                "relationId": "REL_TEST_DOWNSTREAM",
                "regionId": "TEST_REGION_001",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_TEST_A",
                "toEntityType": "road",
                "toEntityId": "ROAD_TEST_B",
                "relationType": "downstream",
                "status": "active",
            },
            {
                "relationId": "REL_TEST_ALTERNATE",
                "regionId": "TEST_REGION_001",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_TEST_A",
                "toEntityType": "road",
                "toEntityId": "ROAD_TEST_B",
                "relationType": "alternate",
                "status": "active",
            },
        ],
        "pois": [
            {
                "poiId": "POI_TEST_SCHOOL",
                "regionId": "TEST_REGION_001",
                "name": "测试小学",
                "type": "school",
                "roadId": "ROAD_TEST_A",
                "intersectionId": "INT_TEST_001",
                "importance": "high",
                "activeHours": {"arrival": ["07:00", "08:00"]},
                "status": "active",
            }
        ],
    }


def _table_count(repo: SQLiteRegionalRepository, table: str) -> int:
    conn = sqlite3.connect(repo.db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _assert_validation_error(func):
    with pytest.raises(RegionalValidationError) as exc:
        func()
    assert exc.value.errors
    return exc.value.errors


def test_create_import_region(repo):
    result = repo.import_context_pack(_base_pack())
    assert result["regionId"] == "TEST_REGION_001"
    assert repo.get_region("TEST_REGION_001")["name"] == "测试试点区域"


def test_road_canonical_identity_persists_without_relation_columns(repo):
    repo.import_context_pack(_base_pack())
    road = repo.get_road("ROAD_TEST_A")
    assert road["regionId"] == "TEST_REGION_001"
    assert road["name"] == "人民路"
    conn = sqlite3.connect(repo.db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(roads)").fetchall()}
    finally:
        conn.close()
    assert "start_intersection_id" not in columns
    assert "end_intersection_id" not in columns
    assert "connected_road_ids" not in columns


def test_intersection_canonical_identity_persists_without_connected_roads(repo):
    repo.import_context_pack(_base_pack())
    intersection = repo.get_intersection("INT_TEST_001")
    assert intersection["name"] == "人民路-解放路路口"
    conn = sqlite3.connect(repo.db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(intersections)").fetchall()}
    finally:
        conn.close()
    assert "connected_road_ids" not in columns


def test_aliases_normalize_deterministically():
    assert normalize_alias(" 人民 路 ") == normalize_alias("人民路")
    assert normalize_alias("人民路与解放路交叉口") == normalize_alias("人民路/解放路路口")
    assert normalize_alias("Ren Min Road") == "renminroad"


def test_same_normalized_alias_same_entity_allowed_idempotent(repo):
    pack = _base_pack()
    pack["roads"][0]["aliases"].extend(["人民路", " 人民 路 "])
    first = repo.import_context_pack(pack)
    second = repo.import_context_pack(pack)
    assert first["inserted"]["roadAliases"] >= 2
    assert second["inserted"]["roadAliases"] == 0


def test_same_normalized_alias_different_entity_rejected(repo):
    pack = _base_pack()
    pack["roads"][1]["aliases"].append("人民 路")
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "alias_conflict" for err in errors)


def test_write_time_road_alias_collision_rolls_back(repo, monkeypatch):
    repo.import_context_pack(_base_pack())
    monkeypatch.setattr(
        SQLiteRegionalRepository,
        "_validate_alias_conflicts",
        lambda self, items, kind, errors: None,
    )
    pack = {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_001",
            "name": "测试试点区域",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {
                "roadId": "ROAD_TEST_C",
                "regionId": "TEST_REGION_001",
                "name": "青年路",
                "aliases": ["人民路"],
            }
        ],
        "intersections": [],
        "roadRelations": [],
        "pois": [],
    }
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "alias_conflict" for err in errors)
    assert repo.get_road("ROAD_TEST_C") is None


def test_write_time_intersection_alias_collision_rolls_back(repo, monkeypatch):
    repo.import_context_pack(_base_pack())
    monkeypatch.setattr(
        SQLiteRegionalRepository,
        "_validate_alias_conflicts",
        lambda self, items, kind, errors: None,
    )
    pack = {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_001",
            "name": "测试试点区域",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [],
        "intersections": [
            {
                "intersectionId": "INT_TEST_002",
                "regionId": "TEST_REGION_001",
                "name": "青年路-和平路路口",
                "aliases": ["人民路与解放路交叉口"],
            }
        ],
        "roadRelations": [],
        "pois": [],
    }
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "alias_conflict" for err in errors)
    assert repo.get_intersection("INT_TEST_002") is None


def test_road_relation_valid_same_region_entities(repo):
    repo.import_context_pack(_base_pack())
    relations = repo.list_relations("TEST_REGION_001", relation_type="connects")
    assert {r["relationId"] for r in relations} == {"REL_TEST_CONNECT_A", "REL_TEST_CONNECT_B"}


def test_cross_region_relation_rejected(repo):
    repo.import_context_pack(_base_pack())
    pack = _base_pack()
    pack["region"]["regionId"] = "TEST_REGION_002"
    pack["region"]["name"] = "测试试点区域二"
    pack["roads"] = []
    pack["intersections"][0]["regionId"] = "TEST_REGION_002"
    pack["intersections"][0]["intersectionId"] = "INT_TEST_002"
    pack["roadRelations"] = [
        {
            "relationId": "REL_CROSS",
            "regionId": "TEST_REGION_002",
            "fromEntityType": "road",
            "fromEntityId": "ROAD_TEST_A",
            "toEntityType": "intersection",
            "toEntityId": "INT_TEST_002",
            "relationType": "connects",
        }
    ]
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "cross_region" for err in errors)


def test_dangling_relation_rejected(repo):
    pack = _base_pack()
    pack["roadRelations"][0]["fromEntityId"] = "ROAD_MISSING"
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "dangling_reference" for err in errors)


def test_poi_bound_to_valid_road_and_intersection(repo):
    repo.import_context_pack(_base_pack())
    pois = repo.list_pois("TEST_REGION_001")
    assert pois[0]["roadId"] == "ROAD_TEST_A"
    assert pois[0]["intersectionId"] == "INT_TEST_001"


def test_cross_region_poi_link_rejected(repo):
    repo.import_context_pack(_base_pack())
    pack = _base_pack()
    pack["region"]["regionId"] = "TEST_REGION_002"
    pack["region"]["name"] = "测试试点区域二"
    pack["roads"][0]["regionId"] = "TEST_REGION_002"
    pack["roads"][0]["roadId"] = "ROAD_TEST_C"
    pack["roads"][0]["name"] = "青年路"
    pack["roads"] = [pack["roads"][0]]
    pack["intersections"] = []
    pack["roadRelations"] = []
    pack["pois"][0]["regionId"] = "TEST_REGION_002"
    pack["pois"][0]["roadId"] = "ROAD_TEST_A"
    pack["pois"][0]["intersectionId"] = None
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "cross_region" for err in errors)


def test_same_package_import_twice_second_new_records_zero(repo):
    repo.import_context_pack(_base_pack())
    second = repo.import_context_pack(_base_pack())
    assert second["totalNewRecords"] == 0


def test_invalid_package_partial_writes_zero(repo):
    pack = _base_pack()
    pack["roadRelations"][0]["toEntityId"] = "INT_MISSING"
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert errors
    assert repo.list_regions() == []
    assert _table_count(repo, "roads") == 0


def test_canonical_ids_stable_across_repeated_import(repo):
    repo.import_context_pack(_base_pack())
    repo.import_context_pack(_base_pack())
    assert {r["roadId"] for r in repo.list_roads("TEST_REGION_001")} == {"ROAD_TEST_A", "ROAD_TEST_B"}
    assert repo.get_intersection("INT_TEST_001")["intersectionId"] == "INT_TEST_001"


def test_synthetic_provenance_remains_synthetic(repo):
    repo.import_context_pack(_base_pack())
    assert repo.get_region("TEST_REGION_001")["verificationStatus"] == "synthetic"
    assert repo.get_road("ROAD_TEST_A")["sourceType"] == "synthetic_fixture"
    assert repo.list_pois("TEST_REGION_001")[0]["verificationStatus"] == "synthetic"


def test_query_intersection_to_connected_roads(repo):
    repo.import_context_pack(_base_pack())
    roads = repo.list_connected_roads_for_intersection("INT_TEST_001")
    assert {road["roadId"] for road in roads} == {"ROAD_TEST_A", "ROAD_TEST_B"}


def test_query_road_to_intersections(repo):
    repo.import_context_pack(_base_pack())
    intersections = repo.list_intersections_for_road("ROAD_TEST_A")
    assert [i["intersectionId"] for i in intersections] == ["INT_TEST_001"]


def test_query_adjacent_upstream_downstream_alternate(repo):
    repo.import_context_pack(_base_pack())
    expected = {
        "adjacent": "REL_TEST_ADJACENT",
        "upstream": "REL_TEST_UPSTREAM",
        "downstream": "REL_TEST_DOWNSTREAM",
        "alternate": "REL_TEST_ALTERNATE",
    }
    for relation_type, relation_id in expected.items():
        relations = repo.list_relations(
            "TEST_REGION_001",
            entity_type="road",
            entity_id="ROAD_TEST_A",
            relation_type=relation_type,
        )
        assert [r["relationId"] for r in relations] == [relation_id]


def test_coordinates_optional(repo):
    pack = _base_pack()
    pack["roads"][0].pop("coordinates", None)
    pack["intersections"][0].pop("latitude", None)
    pack["intersections"][0].pop("longitude", None)
    repo.import_context_pack(pack)
    assert repo.get_road("ROAD_TEST_A")["coordinates"] is None
    assert repo.get_intersection("INT_TEST_001")["latitude"] is None


def test_malformed_metadata_json_package_input_fails_honestly(repo):
    pack = _base_pack()
    pack["region"]["metadataJson"] = "{not valid"
    pack["region"].pop("metadata", None)
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "invalid_json" for err in errors)
    assert repo.list_regions() == []


def test_nan_and_infinite_numeric_values_fail_honestly(repo):
    pack = _base_pack()
    pack["intersections"][0]["latitude"] = float("nan")
    pack["roads"][0]["lengthMeters"] = float("inf")
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["path"] == "intersections[0].latitude" for err in errors)
    assert any(err["path"] == "roads[0].lengthMeters" for err in errors)
    assert repo.list_regions() == []


def test_metadata_json_nan_fails_honestly(repo):
    pack = _base_pack()
    pack["region"]["metadata"] = {"bad": float("inf")}
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "non_finite_json" for err in errors)
    assert repo.list_regions() == []


def test_invalid_relation_semantics_rejected(repo):
    pack = _base_pack()
    pack["roadRelations"].append(
        {
            "relationId": "REL_BAD_SEMANTICS",
            "regionId": "TEST_REGION_001",
            "fromEntityType": "intersection",
            "fromEntityId": "INT_TEST_001",
            "toEntityType": "intersection",
            "toEntityId": "INT_TEST_001",
            "relationType": "upstream",
        }
    )
    errors = _assert_validation_error(lambda: repo.import_context_pack(pack))
    assert any(err["code"] == "invalid_relation_semantics" for err in errors)


def test_bidirectional_connect_relations_do_not_duplicate_query_results(repo):
    pack = _base_pack()
    pack["roadRelations"].append(
        {
            "relationId": "REL_TEST_CONNECT_A_REVERSE",
            "regionId": "TEST_REGION_001",
            "fromEntityType": "intersection",
            "fromEntityId": "INT_TEST_001",
            "toEntityType": "road",
            "toEntityId": "ROAD_TEST_A",
            "relationType": "connects",
            "status": "active",
        }
    )
    repo.import_context_pack(pack)
    roads = repo.list_connected_roads_for_intersection("INT_TEST_001")
    assert [road["roadId"] for road in roads].count("ROAD_TEST_A") == 1
    intersections = repo.list_intersections_for_road("ROAD_TEST_A")
    assert [item["intersectionId"] for item in intersections] == ["INT_TEST_001"]


def test_read_api_import_summary_and_relation_queries(api_client):
    response = api_client.post("/regional/context-packs/import", json=_base_pack())
    assert response.status_code == 200
    assert response.json()["regionId"] == "TEST_REGION_001"

    summary = api_client.get("/regional/regions/TEST_REGION_001/summary").json()
    assert summary["roadCount"] == 2
    assert summary["intersectionCount"] == 1
    assert summary["relationCount"] == 6
    assert summary["poiCount"] == 1

    connected = api_client.get("/regional/intersections/INT_TEST_001/roads").json()
    assert connected["total"] == 2
    road_intersections = api_client.get("/regional/roads/ROAD_TEST_A/intersections").json()
    assert road_intersections["intersections"][0]["intersectionId"] == "INT_TEST_001"


def test_context_pack_directory_loader(tmp_path):
    root = tmp_path / "pilot_region_package"
    root.mkdir()
    pack = _base_pack()
    (root / "package.json").write_text(
        json.dumps({
            "packageVersion": 1,
            "sourceType": "synthetic_fixture",
            "verificationStatus": "synthetic",
        }),
        encoding="utf-8",
    )
    for key, filename in [
        ("region", "region.json"),
        ("roads", "roads.json"),
        ("intersections", "intersections.json"),
        ("roadRelations", "road_relations.json"),
        ("pois", "pois.json"),
    ]:
        (root / filename).write_text(json.dumps(pack[key], ensure_ascii=False), encoding="utf-8")

    loaded = load_context_pack_from_directory(root)
    assert loaded["packageVersion"] == 1
    assert loaded["region"]["regionId"] == "TEST_REGION_001"
    assert loaded["roadRelations"][0]["relationId"] == "REL_TEST_CONNECT_A"


def test_init_regional_tables_idempotent(repo):
    init_regional_tables(repo.db_path)
    init_regional_tables(repo.db_path)
    conn = sqlite3.connect(repo.db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert {
        "regions",
        "roads",
        "road_aliases",
        "intersections",
        "intersection_aliases",
        "road_relations",
        "pois",
    }.issubset(tables)


def test_validation_error_is_product_contract_not_sqlite_exception(api_client):
    pack = _base_pack()
    pack["pois"][0]["type"] = "unmodeled_kind"
    response = api_client.post("/regional/context-packs/import", json=pack)
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "regional_validation_error"
    assert any("pois[0].type" == err["path"] for err in body["detail"]["errors"])
