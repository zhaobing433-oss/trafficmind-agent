"""Phase21 G1 Qiantang pilot context pack validation.

The tests read the formal pilot pack and import it only into temporary SQLite
databases. They must not touch backend/data/trafficmind.db, Knowledge indexes,
historical event logs, or case memory production data.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.regional.importer import load_context_pack_from_directory
from backend.regional.normalization import normalize_alias
from backend.regional.repository import RegionalValidationError, SQLiteRegionalRepository
from backend.regional.resolver import EventLocationBindingService
from backend.tools import db_tools


PACK_DIR = Path(__file__).resolve().parents[1] / "data" / "pilot_regions" / "qt_by_xiasha_pilot_001"
REGION_ID = "QT_BY_XIASHA_PILOT_001"


def _load_pack() -> dict:
    return load_context_pack_from_directory(PACK_DIR)


def _load_source_register() -> dict:
    with (PACK_DIR / "source_register.json").open(encoding="utf-8") as f:
        return json.load(f)


def _table_count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not row or row[0] == 0:
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _source_ids_from_reference(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _entity_source_ids(entity: dict) -> set[str]:
    metadata = entity.get("metadata") or {}
    return set(metadata.get("sourceIds") or []) | _source_ids_from_reference(entity.get("sourceReference", ""))


def test_qiantang_pack_contract_and_source_completeness():
    pack = _load_pack()
    register = _load_source_register()
    source_ids = {source["sourceId"] for source in register["sources"]}

    assert pack["packageVersion"] == 1
    assert pack["region"]["regionId"] == REGION_ID
    assert pack["region"]["metadata"]["notOfficialAdministrativeUnit"] is True
    assert pack["region"]["metadata"]["dataReality"]["historicalEvents"] == "not_included"
    assert pack["region"]["metadata"]["dataReality"]["caseMemory"] == "not_included"
    assert pack["region"]["metadata"]["dataReality"]["officialGIS"] is False
    assert pack["region"]["metadata"]["dataReality"]["realtimeTraffic"] is False
    assert pack["region"]["metadata"]["boundaryMembershipContract"]["type"] == (
        "explicit_inventory_with_open_geo_coordinate_check"
    )

    assert len(pack["roads"]) >= 8
    assert len(pack["intersections"]) >= 8
    assert len(pack["roadRelations"]) >= 12
    assert len(pack["pois"]) >= 8

    road_ids = {road["roadId"] for road in pack["roads"]}
    intersection_ids = {item["intersectionId"] for item in pack["intersections"]}
    bbox = pack["region"]["metadata"]["approximateStudyArea"]
    lng_min, lng_max = bbox["longitudeRange"]
    lat_min, lat_max = bbox["latitudeRange"]

    unverified = []
    for collection in ("roads", "intersections", "roadRelations", "pois"):
        for entity in pack[collection]:
            if entity.get("verificationStatus") != "verified":
                unverified.append(entity)
            assert _entity_source_ids(entity)
            assert _entity_source_ids(entity).issubset(source_ids)
            assert entity.get("sourceReference")
            assert "/Users/" not in json.dumps(entity, ensure_ascii=False)
            assert entity.get("metadata", {}).get("g1VerificationStatus") != "UNVERIFIED"
    assert not unverified

    for intersection in pack["intersections"]:
        assert lat_min <= intersection["latitude"] <= lat_max
        assert lng_min <= intersection["longitude"] <= lng_max
        assert intersection["metadata"]["coordinateSystem"] == "WGS84"
        assert intersection["metadata"]["coordinatePrecision"] == "open_geo_approximate"

    for relation in pack["roadRelations"]:
        endpoints = [
            (relation["fromEntityType"], relation["fromEntityId"]),
            (relation["toEntityType"], relation["toEntityId"]),
        ]
        for entity_type, entity_id in endpoints:
            if entity_type == "road":
                assert entity_id in road_ids
            elif entity_type == "intersection":
                assert entity_id in intersection_ids
            else:
                pytest.fail(f"unexpected relation entity type: {entity_type}")
        assert relation["relationType"] == "connects"
        assert relation["sourceType"] == "derived_from_real_geography"

    for poi in pack["pois"]:
        assert poi["type"] == "school"
        assert poi.get("roadId") in road_ids
        assert not poi.get("intersectionId")
        assert poi["sourceType"] == "first_party"
        assert poi["metadata"]["locationBindingBasis"].endswith("no intersection binding is asserted.")

    tiers = {source["sourceTier"] for source in register["sources"]}
    assert "D" not in tiers
    assert any(source.get("licenseNote", "").find("ODbL") >= 0 for source in register["sources"])
    for source in register["sources"]:
        parsed = urlparse(source["sourceUrl"])
        assert parsed.scheme in {"http", "https"}
        assert parsed.netloc
        tracking_keys = {
            key.lower()
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        }
        assert not any(key.startswith("utm_") or key in {"session", "sid", "token"} for key in tracking_keys)

    readme = (PACK_DIR / "README.md").read_text(encoding="utf-8")
    for required_note in [
        "Source snapshot date: `2026-09-01`",
        "not an official administrative boundary",
        "not official GIS topology",
        "not realtime production traffic data",
        "not a complete Qiantang District road network",
        "not a Qiantang District government partnership dataset",
        "OpenStreetMap contributors",
        "ODbL",
    ]:
        assert required_note in readme


def test_qiantang_pack_import_idempotency_and_no_event_or_case_tables(tmp_path):
    db_path = str(tmp_path / "qt_by_xiasha_g1.db")
    assert db_path != cfg.DB_PATH
    repo = SQLiteRegionalRepository(db_path=db_path)

    first = repo.import_context_pack(_load_pack())
    second = repo.import_context_pack(_load_pack())

    assert first["regionId"] == REGION_ID
    assert first["inserted"]["regions"] == 1
    assert first["inserted"]["roads"] == 11
    assert first["inserted"]["intersections"] == 9
    assert first["inserted"]["roadRelations"] == 18
    assert first["inserted"]["pois"] == 9
    assert first["inserted"]["roadAliases"] + first["inserted"]["intersectionAliases"] >= 6
    assert second["totalNewRecords"] == 0
    assert all(value == 0 for value in second["inserted"].values())

    summary = repo.get_region_summary(REGION_ID)
    assert summary["roadCount"] == 11
    assert summary["intersectionCount"] == 9
    assert summary["relationCount"] == 18
    assert summary["poiCount"] == 9
    assert _table_count(db_path, "event_records") == 0
    assert _table_count(db_path, "traffic_case_memories") == 0


def test_invalid_qiantang_pack_rejects_without_partial_writes(tmp_path):
    db_path = str(tmp_path / "qt_by_xiasha_invalid.db")
    repo = SQLiteRegionalRepository(db_path=db_path)
    invalid = copy.deepcopy(_load_pack())
    invalid["roadRelations"][0]["fromEntityId"] = "QT_BY_RD_MISSING"

    with pytest.raises(RegionalValidationError) as exc:
        repo.import_context_pack(invalid)

    assert any(error.get("code") == "dangling_reference" for error in exc.value.errors)
    assert repo.list_regions() == []
    assert _table_count(db_path, "roads") == 0
    assert _table_count(db_path, "intersections") == 0
    assert _table_count(db_path, "road_relations") == 0
    assert _table_count(db_path, "pois") == 0


def test_alias_collision_and_connectivity_audit():
    pack = _load_pack()
    road_alias_owners: dict[str, str] = {}
    intersection_alias_owners: dict[str, str] = {}

    for road in pack["roads"]:
        aliases = [road["name"], *(road.get("aliases") or [])]
        for alias in aliases:
            normalized = normalize_alias(alias)
            previous = road_alias_owners.get(normalized)
            assert previous in (None, road["roadId"])
            road_alias_owners[normalized] = road["roadId"]

    for intersection in pack["intersections"]:
        aliases = [intersection["name"], *(intersection.get("aliases") or [])]
        for alias in aliases:
            normalized = normalize_alias(alias)
            previous = intersection_alias_owners.get(normalized)
            assert previous in (None, intersection["intersectionId"])
            intersection_alias_owners[normalized] = intersection["intersectionId"]

    assert set(road_alias_owners).isdisjoint(intersection_alias_owners)

    connected_by_intersection: dict[str, set[str]] = {
        item["intersectionId"]: set() for item in pack["intersections"]
    }
    for relation in pack["roadRelations"]:
        if relation["fromEntityType"] == "road":
            road_id = relation["fromEntityId"]
            intersection_id = relation["toEntityId"]
        else:
            road_id = relation["toEntityId"]
            intersection_id = relation["fromEntityId"]
        connected_by_intersection[intersection_id].add(road_id)

    assert all(len(roads) >= 2 for roads in connected_by_intersection.values())


def test_qiantang_resolver_all_names_and_aliases_use_temp_event_records(tmp_path, monkeypatch):
    db_path = str(tmp_path / "qt_by_xiasha_resolver.db")
    assert db_path != cfg.DB_PATH
    repo = SQLiteRegionalRepository(db_path=db_path)
    repo.import_context_pack(_load_pack())
    monkeypatch.setattr(db_tools, "DB_PATH", db_path)

    service = EventLocationBindingService(repo)

    pack = _load_pack()
    samples = []
    for road in pack["roads"]:
        for alias in [road["name"], *(road.get("aliases") or [])]:
            samples.append((f"EVT_ROAD_{len(samples)}", alias, "road", road["roadId"]))
    for intersection in pack["intersections"]:
        for alias in [intersection["name"], *(intersection.get("aliases") or [])]:
            samples.append((
                f"EVT_INT_{len(samples)}",
                alias,
                "intersection",
                intersection["intersectionId"],
            ))

    for event_id, road_name, expected_type, expected_id in samples:
        assert db_tools.save_event_analysis({
            "eventId": event_id,
            "standardEvent": {
                "eventId": event_id,
                "eventType": "congestion",
                "eventTypeCn": "拥堵",
                "roadName": road_name,
            },
            "riskScore": 70,
            "riskLevel": "高风险",
            "status": "待派单",
            "report": "temp resolver smoke only",
            "analyzedAt": "2026-09-01 00:00:00",
        })
        result = service.preview(event_id, region_id=REGION_ID)
        assert result["status"] == "resolved"
        if expected_type == "road":
            assert result["roadId"] == expected_id
            assert result["intersectionId"] is None
        else:
            assert result["intersectionId"] == expected_id
            assert result["roadId"] is None

    assert db_tools.DB_PATH == db_path
    assert len([s for s in samples if s[2] == "road"]) == 31
    assert len([s for s in samples if s[2] == "intersection"]) == 9
