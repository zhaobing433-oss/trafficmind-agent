"""SQLite repository for Phase21 Regional Core.

This module owns Phase21 regional entities:
regions, roads, road_aliases, intersections, intersection_aliases,
road_relations, pois, and event_location_bindings.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import backend.config as _config
from backend.regional.models import (
    VALID_ENTITY_TYPES,
    VALID_POI_TYPES,
    VALID_RELATION_TYPES,
    VALID_VERIFICATION_STATUSES,
    RegionalValidationError,
    validation_error,
)
from backend.regional.normalization import normalize_alias


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or _config.DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_regional_tables(db_path: Optional[str] = None) -> None:
    """Create Phase21 regional tables idempotently."""

    conn = _get_conn(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS regions (
                region_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                district TEXT DEFAULT NULL,
                timezone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                description TEXT DEFAULT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source_type TEXT NOT NULL DEFAULT 'unknown',
                source_reference TEXT DEFAULT '',
                verified_at TEXT DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS roads (
                road_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                name TEXT NOT NULL,
                road_type TEXT DEFAULT NULL,
                direction_mode TEXT DEFAULT NULL,
                length_meters REAL DEFAULT NULL,
                coordinates_json TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source_type TEXT NOT NULL DEFAULT 'unknown',
                source_reference TEXT DEFAULT '',
                verified_at TEXT DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id)
            );

            CREATE TABLE IF NOT EXISTS road_aliases (
                alias_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                road_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id),
                FOREIGN KEY (road_id) REFERENCES roads(road_id),
                UNIQUE(region_id, road_id, alias)
            );

            CREATE TABLE IF NOT EXISTS intersections (
                intersection_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                name TEXT NOT NULL,
                latitude REAL DEFAULT NULL,
                longitude REAL DEFAULT NULL,
                intersection_type TEXT DEFAULT NULL,
                importance TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source_type TEXT NOT NULL DEFAULT 'unknown',
                source_reference TEXT DEFAULT '',
                verified_at TEXT DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id)
            );

            CREATE TABLE IF NOT EXISTS intersection_aliases (
                alias_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                intersection_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id),
                FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id),
                UNIQUE(region_id, intersection_id, alias)
            );

            CREATE TABLE IF NOT EXISTS road_relations (
                relation_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                from_entity_type TEXT NOT NULL,
                from_entity_id TEXT NOT NULL,
                to_entity_type TEXT NOT NULL,
                to_entity_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                direction TEXT DEFAULT NULL,
                distance_meters REAL DEFAULT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                source_type TEXT NOT NULL DEFAULT 'unknown',
                source_reference TEXT DEFAULT '',
                verified_at TEXT DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id)
            );

            CREATE TABLE IF NOT EXISTS pois (
                poi_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                road_id TEXT DEFAULT NULL,
                intersection_id TEXT DEFAULT NULL,
                latitude REAL DEFAULT NULL,
                longitude REAL DEFAULT NULL,
                importance TEXT DEFAULT NULL,
                active_hours_json TEXT DEFAULT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                source_type TEXT NOT NULL DEFAULT 'unknown',
                source_reference TEXT DEFAULT '',
                verified_at TEXT DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id),
                FOREIGN KEY (road_id) REFERENCES roads(road_id),
                FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id)
            );

            CREATE TABLE IF NOT EXISTS event_location_bindings (
                binding_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                region_id TEXT NOT NULL,
                road_id TEXT DEFAULT NULL,
                intersection_id TEXT DEFAULT NULL,
                resolution_method TEXT NOT NULL,
                matched_alias TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'resolved',
                resolved_at TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'deterministic_resolver',
                source_reference TEXT DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (region_id) REFERENCES regions(region_id),
                FOREIGN KEY (road_id) REFERENCES roads(road_id),
                FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id)
            );

            CREATE INDEX IF NOT EXISTS idx_regions_status ON regions(status);
            CREATE INDEX IF NOT EXISTS idx_roads_region ON roads(region_id);
            CREATE INDEX IF NOT EXISTS idx_road_aliases_road ON road_aliases(road_id);
            CREATE INDEX IF NOT EXISTS idx_road_aliases_normalized
                ON road_aliases(region_id, normalized_alias);
            CREATE INDEX IF NOT EXISTS idx_intersections_region ON intersections(region_id);
            CREATE INDEX IF NOT EXISTS idx_intersection_aliases_intersection
                ON intersection_aliases(intersection_id);
            CREATE INDEX IF NOT EXISTS idx_intersection_aliases_normalized
                ON intersection_aliases(region_id, normalized_alias);
            CREATE INDEX IF NOT EXISTS idx_relations_region ON road_relations(region_id);
            CREATE INDEX IF NOT EXISTS idx_relations_from
                ON road_relations(from_entity_type, from_entity_id, relation_type);
            CREATE INDEX IF NOT EXISTS idx_relations_to
                ON road_relations(to_entity_type, to_entity_id, relation_type);
            CREATE INDEX IF NOT EXISTS idx_pois_region ON pois(region_id);
            CREATE INDEX IF NOT EXISTS idx_pois_road ON pois(road_id);
            CREATE INDEX IF NOT EXISTS idx_pois_intersection ON pois(intersection_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_event_location_one_active
                ON event_location_bindings(event_id) WHERE status = 'resolved';
            CREATE INDEX IF NOT EXISTS idx_event_location_event
                ON event_location_bindings(event_id);
            CREATE INDEX IF NOT EXISTS idx_event_location_region
                ON event_location_bindings(region_id);
            CREATE INDEX IF NOT EXISTS idx_event_location_road
                ON event_location_bindings(road_id);
            CREATE INDEX IF NOT EXISTS idx_event_location_intersection
                ON event_location_bindings(intersection_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _json_loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any, *, nullable: bool = False) -> Optional[str]:
    if value is None:
        return None if nullable else "{}"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _require_text(data: Dict[str, Any], key: str, path: str, errors: List[Dict[str, str]]) -> str:
    value = data.get(key)
    if value is None or str(value).strip() == "":
        errors.append(validation_error(f"{path}.{key}", "required non-empty field", "required"))
        return ""
    return str(value).strip()


def _optional_text(data: Dict[str, Any], key: str) -> Optional[str]:
    value = data.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(
    data: Dict[str, Any],
    key: str,
    path: str,
    errors: List[Dict[str, str]],
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    value = data.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        errors.append(validation_error(f"{path}.{key}", "must be a finite number"))
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(validation_error(f"{path}.{key}", "must be a number"))
        return None
    if not math.isfinite(number):
        errors.append(validation_error(f"{path}.{key}", "must be a finite number"))
        return None
    if minimum is not None and number < minimum:
        errors.append(validation_error(f"{path}.{key}", f"must be >= {minimum}"))
    if maximum is not None and number > maximum:
        errors.append(validation_error(f"{path}.{key}", f"must be <= {maximum}"))
    return number


def _json_field(
    data: Dict[str, Any],
    path: str,
    key: str,
    errors: List[Dict[str, str]],
    *,
    default: Any,
    nullable: bool = False,
    aliases: Iterable[str] = (),
) -> Any:
    keys = (key, *aliases)
    raw = None
    found = False
    for candidate in keys:
        if candidate in data:
            raw = data.get(candidate)
            found = True
            break
    if not found or raw is None:
        return None if nullable else default
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(validation_error(f"{path}.{key}", "must be valid JSON", "invalid_json"))
            return None if nullable else default
    if not isinstance(raw, (dict, list)):
        errors.append(validation_error(f"{path}.{key}", "must be a JSON object or array"))
        return None if nullable else default
    _validate_json_value(raw, f"{path}.{key}", errors)
    return raw


def _validate_json_value(value: Any, path: str, errors: List[Dict[str, str]]) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            errors.append(validation_error(path, "must not contain NaN or infinite values", "non_finite_json"))
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _validate_json_value(item, f"{path}[{idx}]", errors)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                errors.append(validation_error(path, "JSON object keys must be strings"))
                continue
            _validate_json_value(item, f"{path}.{key}", errors)
        return
    errors.append(validation_error(path, "must contain only JSON-compatible values"))


def _validate_coordinate_pair(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    try:
        if isinstance(value[0], bool) or isinstance(value[1], bool):
            return False
        lng = float(value[0])
        lat = float(value[1])
    except (TypeError, ValueError):
        return False
    return math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90


def _validate_coordinates_json(
    value: Any,
    path: str,
    errors: List[Dict[str, str]],
) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        lat = value.get("latitude", value.get("lat"))
        lng = value.get("longitude", value.get("lng"))
        if lat is not None:
            try:
                if isinstance(lat, bool):
                    raise TypeError
                lat_f = float(lat)
                if not math.isfinite(lat_f):
                    errors.append(validation_error(path, "latitude must be finite"))
                elif lat_f < -90 or lat_f > 90:
                    errors.append(validation_error(path, "latitude out of range"))
            except (TypeError, ValueError):
                errors.append(validation_error(path, "latitude must be numeric"))
        if lng is not None:
            try:
                if isinstance(lng, bool):
                    raise TypeError
                lng_f = float(lng)
                if not math.isfinite(lng_f):
                    errors.append(validation_error(path, "longitude must be finite"))
                elif lng_f < -180 or lng_f > 180:
                    errors.append(validation_error(path, "longitude out of range"))
            except (TypeError, ValueError):
                errors.append(validation_error(path, "longitude must be numeric"))
        return
    if isinstance(value, list):
        pairs = value
        if pairs and all(isinstance(item, (int, float)) for item in pairs) and len(pairs) == 2:
            pairs = [pairs]
        for item in pairs:
            if isinstance(item, list) and item and isinstance(item[0], list):
                for nested in item:
                    if not _validate_coordinate_pair(nested):
                        errors.append(validation_error(path, "coordinate pair out of range or invalid"))
                        return
            elif not _validate_coordinate_pair(item):
                errors.append(validation_error(path, "coordinate pair out of range or invalid"))
                return
        return
    errors.append(validation_error(path, "coordinates must be JSON object or array"))


def _stable_alias_id(
    kind: str,
    region_id: str,
    entity_id: str,
    normalized: str,
    alias: str = "",
) -> str:
    import hashlib

    raw = f"{kind}:{region_id}:{entity_id}:{normalized}:{alias.strip()}".encode("utf-8")
    return f"{kind}alias_{hashlib.sha1(raw).hexdigest()[:16]}"


class SQLiteRegionalRepository:
    """Repository for Regional Core models."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        init_regional_tables(self.db_path)
        return _get_conn(self.db_path)

    # ── Read API helpers ──────────────────────────────────────────────────

    def get_region(self, region_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM regions WHERE region_id = ?", (region_id,)
            ).fetchone()
            return self._region_dict(row) if row else None
        finally:
            conn.close()

    def list_regions(self) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM regions ORDER BY name, region_id"
            ).fetchall()
            return [self._region_dict(row) for row in rows]
        finally:
            conn.close()

    def get_road(self, road_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM roads WHERE road_id = ?", (road_id,)).fetchone()
            return self._road_dict(row) if row else None
        finally:
            conn.close()

    def list_roads(self, region_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM roads WHERE region_id = ? ORDER BY name, road_id",
                (region_id,),
            ).fetchall()
            return [self._road_dict(row) for row in rows]
        finally:
            conn.close()

    def get_intersection(self, intersection_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM intersections WHERE intersection_id = ?",
                (intersection_id,),
            ).fetchone()
            return self._intersection_dict(row) if row else None
        finally:
            conn.close()

    def list_intersections(self, region_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM intersections WHERE region_id = ? ORDER BY name, intersection_id",
                (region_id,),
            ).fetchall()
            return [self._intersection_dict(row) for row in rows]
        finally:
            conn.close()

    def list_relations(
        self,
        region_id: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        relation_type: str = "",
    ) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            clauses = ["region_id = ?"]
            params: List[Any] = [region_id]
            if relation_type:
                clauses.append("relation_type = ?")
                params.append(relation_type)
            if entity_type and entity_id:
                clauses.append(
                    "((from_entity_type = ? AND from_entity_id = ?) OR "
                    "(to_entity_type = ? AND to_entity_id = ?))"
                )
                params.extend([entity_type, entity_id, entity_type, entity_id])
            rows = conn.execute(
                f"SELECT * FROM road_relations WHERE {' AND '.join(clauses)} "
                "ORDER BY relation_type, relation_id",
                params,
            ).fetchall()
            return [self._relation_dict(row) for row in rows]
        finally:
            conn.close()

    def list_connected_roads_for_intersection(self, intersection_id: str) -> List[Dict[str, Any]]:
        intersection = self.get_intersection(intersection_id)
        if not intersection:
            return []
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT r.* FROM road_relations rr
                JOIN roads r ON (
                    (rr.from_entity_type = 'road' AND rr.from_entity_id = r.road_id)
                    OR (rr.to_entity_type = 'road' AND rr.to_entity_id = r.road_id)
                )
                WHERE rr.region_id = ?
                  AND rr.relation_type = 'connects'
                  AND (
                    (rr.from_entity_type = 'intersection' AND rr.from_entity_id = ?)
                    OR (rr.to_entity_type = 'intersection' AND rr.to_entity_id = ?)
                  )
                ORDER BY r.name, r.road_id
                """,
                (intersection["regionId"], intersection_id, intersection_id),
            ).fetchall()
            return [self._road_dict(row) for row in rows]
        finally:
            conn.close()

    def list_intersections_for_road(self, road_id: str) -> List[Dict[str, Any]]:
        road = self.get_road(road_id)
        if not road:
            return []
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT i.* FROM road_relations rr
                JOIN intersections i ON (
                    (rr.from_entity_type = 'intersection' AND rr.from_entity_id = i.intersection_id)
                    OR (rr.to_entity_type = 'intersection' AND rr.to_entity_id = i.intersection_id)
                )
                WHERE rr.region_id = ?
                  AND rr.relation_type = 'connects'
                  AND (
                    (rr.from_entity_type = 'road' AND rr.from_entity_id = ?)
                    OR (rr.to_entity_type = 'road' AND rr.to_entity_id = ?)
                  )
                ORDER BY i.name, i.intersection_id
                """,
                (road["regionId"], road_id, road_id),
            ).fetchall()
            return [self._intersection_dict(row) for row in rows]
        finally:
            conn.close()

    def list_pois(self, region_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM pois WHERE region_id = ? ORDER BY importance DESC, name, poi_id",
                (region_id,),
            ).fetchall()
            return [self._poi_dict(row) for row in rows]
        finally:
            conn.close()

    def list_pois_for_location(
        self,
        region_id: str,
        *,
        road_id: Optional[str] = None,
        intersection_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return explicitly linked POIs; no coordinate-radius inference."""

        if not road_id and not intersection_id:
            return []
        conn = self._conn()
        try:
            clauses = ["region_id = ?"]
            params: List[Any] = [region_id]
            link_clauses: List[str] = []
            if road_id:
                link_clauses.append("road_id = ?")
                params.append(road_id)
            if intersection_id:
                link_clauses.append("intersection_id = ?")
                params.append(intersection_id)
            clauses.append(f"({' OR '.join(link_clauses)})")
            rows = conn.execute(
                f"SELECT * FROM pois WHERE {' AND '.join(clauses)} "
                "ORDER BY importance DESC, name, poi_id",
                params,
            ).fetchall()
            return [self._poi_dict(row) for row in rows]
        finally:
            conn.close()

    def get_region_summary(self, region_id: str) -> Optional[Dict[str, Any]]:
        region = self.get_region(region_id)
        if not region:
            return None
        conn = self._conn()
        try:
            counts = {}
            for key, table in [
                ("roadCount", "roads"),
                ("intersectionCount", "intersections"),
                ("relationCount", "road_relations"),
                ("poiCount", "pois"),
            ]:
                counts[key] = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE region_id = ?",
                    (region_id,),
                ).fetchone()["c"]
            return {"region": region, **counts}
        finally:
            conn.close()

    def find_intersection_alias_matches(
        self,
        value: str,
        *,
        region_id: str = "",
        normalized: bool = False,
    ) -> List[Dict[str, Any]]:
        return self._find_alias_matches(
            "intersection",
            value,
            region_id=region_id,
            normalized=normalized,
        )

    def find_road_alias_matches(
        self,
        value: str,
        *,
        region_id: str = "",
        normalized: bool = False,
    ) -> List[Dict[str, Any]]:
        return self._find_alias_matches(
            "road",
            value,
            region_id=region_id,
            normalized=normalized,
        )

    def _find_alias_matches(
        self,
        kind: str,
        value: str,
        *,
        region_id: str,
        normalized: bool,
    ) -> List[Dict[str, Any]]:
        text = normalize_alias(value) if normalized else str(value or "").strip()
        if not text:
            return []
        if kind == "intersection":
            alias_table = "intersection_aliases"
            entity_table = "intersections"
            entity_column = "intersection_id"
            select_columns = "e.intersection_id AS entity_id, e.name AS entity_name"
        else:
            alias_table = "road_aliases"
            entity_table = "roads"
            entity_column = "road_id"
            select_columns = "e.road_id AS entity_id, e.name AS entity_name"

        field = "a.normalized_alias" if normalized else "a.alias"
        clauses = [f"{field} = ?"]
        params: List[Any] = [text]
        if region_id:
            clauses.append("a.region_id = ?")
            params.append(region_id)

        conn = self._conn()
        try:
            rows = conn.execute(
                f"""
                SELECT
                    a.region_id,
                    a.alias,
                    a.normalized_alias,
                    {select_columns}
                FROM {alias_table} a
                JOIN {entity_table} e ON e.{entity_column} = a.{entity_column}
                WHERE {' AND '.join(clauses)}
                ORDER BY a.region_id, a.alias
                """,
                params,
            ).fetchall()
            result = []
            for row in rows:
                item = {
                    "regionId": row["region_id"],
                    "matchedAlias": row["alias"],
                    "normalizedAlias": row["normalized_alias"],
                    "name": row["entity_name"],
                }
                if kind == "intersection":
                    item["intersectionId"] = row["entity_id"]
                else:
                    item["roadId"] = row["entity_id"]
                result.append(item)
            return result
        finally:
            conn.close()

    def get_active_event_location_binding(self, event_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            row = conn.execute(
                """
                SELECT * FROM event_location_bindings
                WHERE event_id = ? AND status = 'resolved'
                ORDER BY resolved_at DESC, created_at DESC
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
            return self._binding_dict(row) if row else None
        finally:
            conn.close()

    def list_event_location_bindings(self, event_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM event_location_bindings
                WHERE event_id = ?
                ORDER BY created_at DESC, binding_id DESC
                """,
                (event_id,),
            ).fetchall()
            return [self._binding_dict(row) for row in rows]
        finally:
            conn.close()

    def save_resolved_event_location_binding(
        self,
        resolution: Dict[str, Any],
        *,
        source_type: str = "deterministic_resolver",
        source_reference: str = "EventLocationResolver",
        re_resolve: bool = False,
    ) -> Dict[str, Any]:
        if resolution.get("status") != "resolved":
            raise RegionalValidationError([
                validation_error("resolution.status", "only resolved locations can be persisted")
            ])

        event_id = str(resolution.get("eventId") or "").strip()
        region_id = str(resolution.get("regionId") or "").strip()
        road_id = str(resolution.get("roadId") or "").strip() or None
        intersection_id = str(resolution.get("intersectionId") or "").strip() or None
        if not event_id or not region_id or (not road_id and not intersection_id):
            raise RegionalValidationError([
                validation_error("resolution", "eventId, regionId, and one canonical location are required")
            ])

        init_regional_tables(self.db_path)
        conn = _get_conn(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_binding_entities_conn(conn, region_id, road_id, intersection_id)
            active = conn.execute(
                """
                SELECT * FROM event_location_bindings
                WHERE event_id = ? AND status = 'resolved'
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
            if active:
                active_dict = self._binding_dict(active)
                if (
                    active_dict["regionId"] == region_id
                    and active_dict.get("roadId") == road_id
                    and active_dict.get("intersectionId") == intersection_id
                    and active_dict["resolutionMethod"] == resolution["resolutionMethod"]
                ):
                    conn.commit()
                    active_dict["idempotent"] = True
                    return active_dict
                if not re_resolve:
                    raise RegionalValidationError([
                        validation_error(
                            "eventId",
                            "active binding differs; explicit reResolve is required",
                            "binding_changed_requires_reresolution",
                        )
                    ])
                conn.execute(
                    """
                    UPDATE event_location_bindings
                    SET status = 'superseded', updated_at = ?
                    WHERE binding_id = ?
                    """,
                    (_utc_now_iso(), active_dict["bindingId"]),
                )

            now = _utc_now_iso()
            binding_id = self._next_binding_id_conn(conn, event_id)
            metadata = {
                "resolverStatus": resolution.get("status"),
                "candidates": resolution.get("candidates", []),
            }
            conn.execute(
                """
                INSERT INTO event_location_bindings (
                    binding_id, event_id, region_id, road_id, intersection_id,
                    resolution_method, matched_alias, status, resolved_at,
                    source_type, source_reference, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'resolved', ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding_id,
                    event_id,
                    region_id,
                    road_id,
                    intersection_id,
                    resolution["resolutionMethod"],
                    resolution.get("matchedAlias") or "",
                    now,
                    source_type,
                    source_reference,
                    _json_dumps(metadata),
                    now,
                    now,
                ),
            )
            conn.commit()
            binding = self.get_active_event_location_binding(event_id)
            if binding is None:
                raise RegionalValidationError([
                    validation_error("eventId", "binding persistence failed")
                ])
            binding["idempotent"] = False
            return binding
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def build_regional_location_context(self, binding: Dict[str, Any]) -> Dict[str, Any]:
        region_id = binding["regionId"]
        road_id = binding.get("roadId")
        intersection_id = binding.get("intersectionId")
        region = self.get_region(region_id)
        road = self.get_road(road_id) if road_id else None
        intersection = self.get_intersection(intersection_id) if intersection_id else None
        connected_roads = (
            self.list_connected_roads_for_intersection(intersection_id)
            if intersection_id
            else []
        )
        nearby_pois = self.list_pois_for_location(
            region_id,
            road_id=road_id,
            intersection_id=intersection_id,
        )
        return {
            "region": region,
            "road": road,
            "intersection": intersection,
            "connectedRoads": connected_roads,
            "nearbyPois": nearby_pois,
        }

    # ── Import ────────────────────────────────────────────────────────────

    def import_context_pack(self, package: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_package(package)
        errors = self._validate_package(normalized)
        if errors:
            raise RegionalValidationError(errors)

        init_regional_tables(self.db_path)
        conn = _get_conn(self.db_path)
        inserted = {
            "regions": 0,
            "roads": 0,
            "roadAliases": 0,
            "intersections": 0,
            "intersectionAliases": 0,
            "roadRelations": 0,
            "pois": 0,
        }
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = _utc_now_iso()
            inserted["regions"] += self._upsert_region(conn, normalized["region"], now)
            for road in normalized["roads"]:
                inserted["roads"] += self._upsert_road(conn, road, now)
                for alias in road["aliases"]:
                    inserted["roadAliases"] += self._upsert_road_alias(conn, road, alias, now)
            for intersection in normalized["intersections"]:
                inserted["intersections"] += self._upsert_intersection(conn, intersection, now)
                for alias in intersection["aliases"]:
                    inserted["intersectionAliases"] += self._upsert_intersection_alias(
                        conn, intersection, alias, now
                    )
            for relation in normalized["relations"]:
                inserted["roadRelations"] += self._upsert_relation(conn, relation, now)
            for poi in normalized["pois"]:
                inserted["pois"] += self._upsert_poi(conn, poi, now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        total_new = sum(inserted.values())
        return {
            "packageVersion": normalized["packageVersion"],
            "regionId": normalized["region"]["regionId"],
            "inserted": inserted,
            "totalNewRecords": total_new,
        }

    def _normalize_package(self, package: Dict[str, Any]) -> Dict[str, Any]:
        errors: List[Dict[str, str]] = []
        if not isinstance(package, dict):
            raise RegionalValidationError([
                validation_error("package", "must be a JSON object")
            ])
        version = package.get("packageVersion")
        if version != 1:
            errors.append(validation_error("packageVersion", "must be 1", "unsupported_version"))

        region_raw = package.get("region")
        if not isinstance(region_raw, dict):
            errors.append(validation_error("region", "required JSON object", "required"))
            raise RegionalValidationError(errors)

        package_source = _optional_text(package, "sourceType") or "unknown"
        package_reference = _optional_text(package, "sourceReference") or ""
        package_verified = _optional_text(package, "verificationStatus") or "unverified"
        region = self._normalize_region(
            region_raw,
            package_source,
            package_reference,
            package_verified,
            errors,
        )
        region_id = region["regionId"]
        roads = [
            self._normalize_road(item, idx, region_id, package_source, package_reference, package_verified, errors)
            for idx, item in enumerate(package.get("roads") or [])
        ]
        intersections = [
            self._normalize_intersection(
                item, idx, region_id, package_source, package_reference, package_verified, errors
            )
            for idx, item in enumerate(package.get("intersections") or [])
        ]
        raw_relations = package.get("roadRelations", package.get("relations", package.get("road_relations", [])))
        relations = [
            self._normalize_relation(
                item, idx, region_id, package_source, package_reference, package_verified, errors
            )
            for idx, item in enumerate(raw_relations or [])
        ]
        pois = [
            self._normalize_poi(item, idx, region_id, package_source, package_reference, package_verified, errors)
            for idx, item in enumerate(package.get("pois") or [])
        ]
        if errors:
            raise RegionalValidationError(errors)
        return {
            "packageVersion": version,
            "region": region,
            "roads": roads,
            "intersections": intersections,
            "relations": relations,
            "pois": pois,
        }

    def _normalize_region(
        self,
        item: Dict[str, Any],
        package_source: str,
        package_reference: str,
        package_verified: str,
        errors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        path = "region"
        source_type = _optional_text(item, "sourceType") or package_source
        verification_status = _optional_text(item, "verificationStatus") or package_verified
        self._validate_verification(verification_status, f"{path}.verificationStatus", errors)
        metadata = _json_field(item, path, "metadata", errors, default={}, aliases=("metadataJson",))
        return {
            "regionId": _require_text(item, "regionId", path, errors),
            "name": _require_text(item, "name", path, errors),
            "city": _require_text(item, "city", path, errors),
            "district": _optional_text(item, "district"),
            "timezone": _require_text(item, "timezone", path, errors),
            "status": _optional_text(item, "status") or "active",
            "description": _optional_text(item, "description"),
            "metadata": metadata,
            "sourceType": source_type,
            "sourceReference": _optional_text(item, "sourceReference") or package_reference,
            "verifiedAt": _optional_text(item, "verifiedAt") or "",
            "verificationStatus": verification_status,
        }

    def _normalize_road(
        self,
        item: Any,
        idx: int,
        region_id: str,
        package_source: str,
        package_reference: str,
        package_verified: str,
        errors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        path = f"roads[{idx}]"
        if not isinstance(item, dict):
            errors.append(validation_error(path, "must be a JSON object"))
            item = {}
        source_type = _optional_text(item, "sourceType") or package_source
        verification_status = _optional_text(item, "verificationStatus") or package_verified
        self._validate_verification(verification_status, f"{path}.verificationStatus", errors)
        metadata = _json_field(item, path, "metadata", errors, default={}, aliases=("metadataJson",))
        coordinates = _json_field(
            item, path, "coordinates", errors, default=None, nullable=True, aliases=("coordinatesJson",)
        )
        _validate_coordinates_json(coordinates, f"{path}.coordinates", errors)
        aliases = self._normalize_alias_list(
            "road",
            item,
            path,
            "roadId",
            errors,
        )
        return {
            "roadId": _require_text(item, "roadId", path, errors),
            "regionId": _optional_text(item, "regionId") or region_id,
            "name": _require_text(item, "name", path, errors),
            "roadType": _optional_text(item, "roadType"),
            "directionMode": _optional_text(item, "directionMode"),
            "lengthMeters": _optional_float(item, "lengthMeters", path, errors, minimum=0),
            "coordinates": coordinates,
            "status": _optional_text(item, "status") or "active",
            "metadata": metadata,
            "sourceType": source_type,
            "sourceReference": _optional_text(item, "sourceReference") or package_reference,
            "verifiedAt": _optional_text(item, "verifiedAt") or "",
            "verificationStatus": verification_status,
            "aliases": aliases,
        }

    def _normalize_intersection(
        self,
        item: Any,
        idx: int,
        region_id: str,
        package_source: str,
        package_reference: str,
        package_verified: str,
        errors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        path = f"intersections[{idx}]"
        if not isinstance(item, dict):
            errors.append(validation_error(path, "must be a JSON object"))
            item = {}
        source_type = _optional_text(item, "sourceType") or package_source
        verification_status = _optional_text(item, "verificationStatus") or package_verified
        self._validate_verification(verification_status, f"{path}.verificationStatus", errors)
        metadata = _json_field(item, path, "metadata", errors, default={}, aliases=("metadataJson",))
        aliases = self._normalize_alias_list(
            "intersection",
            item,
            path,
            "intersectionId",
            errors,
        )
        return {
            "intersectionId": _require_text(item, "intersectionId", path, errors),
            "regionId": _optional_text(item, "regionId") or region_id,
            "name": _require_text(item, "name", path, errors),
            "latitude": _optional_float(item, "latitude", path, errors, minimum=-90, maximum=90),
            "longitude": _optional_float(item, "longitude", path, errors, minimum=-180, maximum=180),
            "intersectionType": _optional_text(item, "intersectionType"),
            "importance": _optional_text(item, "importance"),
            "status": _optional_text(item, "status") or "active",
            "metadata": metadata,
            "sourceType": source_type,
            "sourceReference": _optional_text(item, "sourceReference") or package_reference,
            "verifiedAt": _optional_text(item, "verifiedAt") or "",
            "verificationStatus": verification_status,
            "aliases": aliases,
        }

    def _normalize_relation(
        self,
        item: Any,
        idx: int,
        region_id: str,
        package_source: str,
        package_reference: str,
        package_verified: str,
        errors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        path = f"roadRelations[{idx}]"
        if not isinstance(item, dict):
            errors.append(validation_error(path, "must be a JSON object"))
            item = {}
        source_type = _optional_text(item, "sourceType") or package_source
        verification_status = _optional_text(item, "verificationStatus") or package_verified
        self._validate_verification(verification_status, f"{path}.verificationStatus", errors)
        metadata = _json_field(item, path, "metadata", errors, default={}, aliases=("metadataJson",))
        relation = {
            "relationId": _require_text(item, "relationId", path, errors),
            "regionId": _optional_text(item, "regionId") or region_id,
            "fromEntityType": _require_text(item, "fromEntityType", path, errors),
            "fromEntityId": _require_text(item, "fromEntityId", path, errors),
            "toEntityType": _require_text(item, "toEntityType", path, errors),
            "toEntityId": _require_text(item, "toEntityId", path, errors),
            "relationType": _require_text(item, "relationType", path, errors),
            "direction": _optional_text(item, "direction"),
            "distanceMeters": _optional_float(item, "distanceMeters", path, errors, minimum=0),
            "metadata": metadata,
            "status": _optional_text(item, "status") or "active",
            "sourceType": source_type,
            "sourceReference": _optional_text(item, "sourceReference") or package_reference,
            "verifiedAt": _optional_text(item, "verifiedAt") or "",
            "verificationStatus": verification_status,
        }
        return relation

    def _normalize_poi(
        self,
        item: Any,
        idx: int,
        region_id: str,
        package_source: str,
        package_reference: str,
        package_verified: str,
        errors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        path = f"pois[{idx}]"
        if not isinstance(item, dict):
            errors.append(validation_error(path, "must be a JSON object"))
            item = {}
        source_type = _optional_text(item, "sourceType") or package_source
        verification_status = _optional_text(item, "verificationStatus") or package_verified
        self._validate_verification(verification_status, f"{path}.verificationStatus", errors)
        metadata = _json_field(item, path, "metadata", errors, default={}, aliases=("metadataJson",))
        active_hours = _json_field(
            item, path, "activeHours", errors, default=None, nullable=True, aliases=("activeHoursJson",)
        )
        return {
            "poiId": _require_text(item, "poiId", path, errors),
            "regionId": _optional_text(item, "regionId") or region_id,
            "name": _require_text(item, "name", path, errors),
            "type": _require_text(item, "type", path, errors),
            "roadId": _optional_text(item, "roadId"),
            "intersectionId": _optional_text(item, "intersectionId"),
            "latitude": _optional_float(item, "latitude", path, errors, minimum=-90, maximum=90),
            "longitude": _optional_float(item, "longitude", path, errors, minimum=-180, maximum=180),
            "importance": _optional_text(item, "importance"),
            "activeHours": active_hours,
            "metadata": metadata,
            "status": _optional_text(item, "status") or "active",
            "sourceType": source_type,
            "sourceReference": _optional_text(item, "sourceReference") or package_reference,
            "verifiedAt": _optional_text(item, "verifiedAt") or "",
            "verificationStatus": verification_status,
        }

    def _normalize_alias_list(
        self,
        kind: str,
        item: Dict[str, Any],
        path: str,
        id_field: str,
        errors: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        aliases: List[str] = []
        name = item.get("name")
        if name:
            aliases.append(str(name))
        raw_aliases = item.get("aliases") or []
        if raw_aliases and not isinstance(raw_aliases, list):
            errors.append(validation_error(f"{path}.aliases", "must be an array"))
            raw_aliases = []
        aliases.extend(str(a) for a in raw_aliases if str(a).strip())
        entity_id = str(item.get(id_field) or "").strip()
        seen = set()
        normalized_aliases: List[Dict[str, str]] = []
        for alias in aliases:
            clean_alias = alias.strip()
            normalized = normalize_alias(alias)
            if not normalized:
                continue
            key = (clean_alias, normalized)
            if key in seen:
                continue
            seen.add(key)
            normalized_aliases.append({
                "alias": clean_alias,
                "normalizedAlias": normalized,
                "aliasId": _stable_alias_id(
                    kind,
                    item.get("regionId") or "",
                    entity_id,
                    normalized,
                    clean_alias,
                ),
            })
        return normalized_aliases

    def _validate_verification(
        self,
        value: str,
        path: str,
        errors: List[Dict[str, str]],
    ) -> None:
        if value not in VALID_VERIFICATION_STATUSES:
            errors.append(
                validation_error(path, "must be verified, unverified, or synthetic", "invalid_enum")
            )

    def _validate_package(self, package: Dict[str, Any]) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        region = package["region"]
        region_id = region["regionId"]
        self._validate_duplicate_ids(package["roads"], "roadId", "roads", errors)
        self._validate_duplicate_ids(package["intersections"], "intersectionId", "intersections", errors)
        self._validate_duplicate_ids(package["relations"], "relationId", "roadRelations", errors)
        self._validate_duplicate_ids(package["pois"], "poiId", "pois", errors)
        for collection_name in ("roads", "intersections", "relations", "pois"):
            for idx, item in enumerate(package[collection_name]):
                if item.get("regionId") != region_id:
                    errors.append(
                        validation_error(
                            f"{collection_name}[{idx}].regionId",
                            "must match package regionId",
                            "cross_region",
                        )
                    )

        road_regions = self._entity_regions("roads", "road_id")
        intersection_regions = self._entity_regions("intersections", "intersection_id")
        for road in package["roads"]:
            road_regions[road["roadId"]] = road["regionId"]
        for intersection in package["intersections"]:
            intersection_regions[intersection["intersectionId"]] = intersection["regionId"]

        self._validate_existing_identity_conflicts(package, errors)
        self._validate_alias_conflicts(package["roads"], "road", errors)
        self._validate_alias_conflicts(package["intersections"], "intersection", errors)
        self._validate_relations(package["relations"], region_id, road_regions, intersection_regions, errors)
        self._validate_pois(package["pois"], region_id, road_regions, intersection_regions, errors)
        return errors

    def _validate_duplicate_ids(
        self,
        items: List[Dict[str, Any]],
        id_field: str,
        path: str,
        errors: List[Dict[str, str]],
    ) -> None:
        seen = set()
        for idx, item in enumerate(items):
            entity_id = item.get(id_field)
            if entity_id in seen:
                errors.append(validation_error(f"{path}[{idx}].{id_field}", "duplicate canonical ID"))
            seen.add(entity_id)

    def _entity_regions(self, table: str, id_column: str) -> Dict[str, str]:
        conn = self._conn()
        try:
            rows = conn.execute(f"SELECT {id_column} AS id, region_id FROM {table}").fetchall()
            return {row["id"]: row["region_id"] for row in rows}
        finally:
            conn.close()

    def _validate_existing_identity_conflicts(
        self,
        package: Dict[str, Any],
        errors: List[Dict[str, str]],
    ) -> None:
        existing_region = self.get_region(package["region"]["regionId"])
        if existing_region and (
            existing_region["name"] != package["region"]["name"]
            or existing_region["city"] != package["region"]["city"]
        ):
            errors.append(validation_error("region", "canonical region identity conflicts with existing row"))

        for path, getter, id_field, immutable_fields, items in [
            ("roads", self.get_road, "roadId", ("regionId", "name"), package["roads"]),
            (
                "intersections",
                self.get_intersection,
                "intersectionId",
                ("regionId", "name"),
                package["intersections"],
            ),
        ]:
            for idx, item in enumerate(items):
                existing = getter(item[id_field])
                if existing and any(existing.get(field) != item.get(field) for field in immutable_fields):
                    errors.append(
                        validation_error(
                            f"{path}[{idx}].{id_field}",
                            "canonical identity conflicts with existing row",
                        )
                    )
        for idx, relation in enumerate(package["relations"]):
            existing = self._get_relation(relation["relationId"])
            immutable = (
                "regionId",
                "fromEntityType",
                "fromEntityId",
                "toEntityType",
                "toEntityId",
                "relationType",
            )
            if existing and any(existing.get(field) != relation.get(field) for field in immutable):
                errors.append(
                    validation_error(
                        f"roadRelations[{idx}].relationId",
                        "canonical relation identity conflicts with existing row",
                    )
                )
        for idx, poi in enumerate(package["pois"]):
            existing = self._get_poi(poi["poiId"])
            immutable = ("regionId", "name", "type")
            if existing and any(existing.get(field) != poi.get(field) for field in immutable):
                errors.append(
                    validation_error(
                        f"pois[{idx}].poiId",
                        "canonical POI identity conflicts with existing row",
                    )
                )

    def _validate_alias_conflicts(
        self,
        items: List[Dict[str, Any]],
        kind: str,
        errors: List[Dict[str, str]],
    ) -> None:
        alias_owner: Dict[Tuple[str, str], str] = {}
        id_field = "roadId" if kind == "road" else "intersectionId"
        table = "road_aliases" if kind == "road" else "intersection_aliases"
        entity_column = "road_id" if kind == "road" else "intersection_id"
        for idx, item in enumerate(items):
            for alias in item["aliases"]:
                key = (item["regionId"], alias["normalizedAlias"])
                previous = alias_owner.get(key)
                if previous and previous != item[id_field]:
                    errors.append(
                        validation_error(
                            f"{kind}s[{idx}].aliases",
                            "same normalized alias points to different entities in package",
                            "alias_conflict",
                        )
                    )
                alias_owner[key] = item[id_field]
                existing = self._find_alias_conflict(table, key[0], key[1], item[id_field], entity_column)
                if existing:
                    errors.append(
                        validation_error(
                            f"{kind}s[{idx}].aliases",
                            "same normalized alias already points to a different entity",
                            "alias_conflict",
                        )
                    )

    def _validate_relations(
        self,
        relations: List[Dict[str, Any]],
        region_id: str,
        road_regions: Dict[str, str],
        intersection_regions: Dict[str, str],
        errors: List[Dict[str, str]],
    ) -> None:
        for idx, relation in enumerate(relations):
            path = f"roadRelations[{idx}]"
            if relation["fromEntityType"] not in VALID_ENTITY_TYPES:
                errors.append(validation_error(f"{path}.fromEntityType", "unknown entity type"))
            if relation["toEntityType"] not in VALID_ENTITY_TYPES:
                errors.append(validation_error(f"{path}.toEntityType", "unknown entity type"))
            if relation["relationType"] not in VALID_RELATION_TYPES:
                errors.append(validation_error(f"{path}.relationType", "unknown relation type"))
            self._validate_relation_endpoint(
                relation["fromEntityType"],
                relation["fromEntityId"],
                region_id,
                road_regions,
                intersection_regions,
                f"{path}.fromEntityId",
                errors,
            )
            self._validate_relation_endpoint(
                relation["toEntityType"],
                relation["toEntityId"],
                region_id,
                road_regions,
                intersection_regions,
                f"{path}.toEntityId",
                errors,
            )
            if not self._relation_semantics_allowed(relation):
                errors.append(
                    validation_error(
                        f"{path}.relationType",
                        "relation type is not valid for this entity combination",
                        "invalid_relation_semantics",
                    )
                )

    def _validate_relation_endpoint(
        self,
        entity_type: str,
        entity_id: str,
        region_id: str,
        road_regions: Dict[str, str],
        intersection_regions: Dict[str, str],
        path: str,
        errors: List[Dict[str, str]],
    ) -> None:
        if entity_type == "road":
            actual_region = road_regions.get(entity_id)
        elif entity_type == "intersection":
            actual_region = intersection_regions.get(entity_id)
        else:
            return
        if actual_region is None:
            errors.append(validation_error(path, "referenced entity does not exist", "dangling_reference"))
        elif actual_region != region_id:
            errors.append(validation_error(path, "referenced entity belongs to another region", "cross_region"))

    def _relation_semantics_allowed(self, relation: Dict[str, Any]) -> bool:
        pair = {relation["fromEntityType"], relation["toEntityType"]}
        if relation["relationType"] == "connects":
            return pair == {"road", "intersection"}
        if relation["relationType"] in {"upstream", "downstream", "adjacent", "alternate"}:
            return relation["fromEntityType"] == "road" and relation["toEntityType"] == "road"
        return False

    def _validate_pois(
        self,
        pois: List[Dict[str, Any]],
        region_id: str,
        road_regions: Dict[str, str],
        intersection_regions: Dict[str, str],
        errors: List[Dict[str, str]],
    ) -> None:
        for idx, poi in enumerate(pois):
            path = f"pois[{idx}]"
            if poi["type"] not in VALID_POI_TYPES:
                errors.append(validation_error(f"{path}.type", "unknown POI type"))
            if poi.get("roadId"):
                road_region = road_regions.get(poi["roadId"])
                if road_region is None:
                    errors.append(validation_error(f"{path}.roadId", "referenced road does not exist"))
                elif road_region != region_id:
                    errors.append(validation_error(f"{path}.roadId", "road belongs to another region", "cross_region"))
            if poi.get("intersectionId"):
                intersection_region = intersection_regions.get(poi["intersectionId"])
                if intersection_region is None:
                    errors.append(validation_error(f"{path}.intersectionId", "referenced intersection does not exist"))
                elif intersection_region != region_id:
                    errors.append(
                        validation_error(
                            f"{path}.intersectionId",
                            "intersection belongs to another region",
                            "cross_region",
                        )
                    )

    def _upsert_region(self, conn: sqlite3.Connection, region: Dict[str, Any], now: str) -> int:
        existed = self._exists_conn(conn, "regions", "region_id", region["regionId"])
        conn.execute(
            """
            INSERT INTO regions (
                region_id, name, city, district, timezone, status, description,
                metadata_json, source_type, source_reference, verified_at,
                verification_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(region_id) DO UPDATE SET
                district=excluded.district,
                timezone=excluded.timezone,
                status=excluded.status,
                description=excluded.description,
                metadata_json=excluded.metadata_json,
                source_type=excluded.source_type,
                source_reference=excluded.source_reference,
                verified_at=excluded.verified_at,
                verification_status=excluded.verification_status,
                updated_at=excluded.updated_at
            """,
            (
                region["regionId"],
                region["name"],
                region["city"],
                region["district"],
                region["timezone"],
                region["status"],
                region["description"],
                _json_dumps(region["metadata"]),
                region["sourceType"],
                region["sourceReference"],
                region["verifiedAt"],
                region["verificationStatus"],
                now,
                now,
            ),
        )
        return 0 if existed else 1

    def _upsert_road(self, conn: sqlite3.Connection, road: Dict[str, Any], now: str) -> int:
        existed = self._exists_conn(conn, "roads", "road_id", road["roadId"])
        conn.execute(
            """
            INSERT INTO roads (
                road_id, region_id, name, road_type, direction_mode, length_meters,
                coordinates_json, status, metadata_json, source_type, source_reference,
                verified_at, verification_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(road_id) DO UPDATE SET
                road_type=excluded.road_type,
                direction_mode=excluded.direction_mode,
                length_meters=excluded.length_meters,
                coordinates_json=excluded.coordinates_json,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                source_type=excluded.source_type,
                source_reference=excluded.source_reference,
                verified_at=excluded.verified_at,
                verification_status=excluded.verification_status,
                updated_at=excluded.updated_at
            """,
            (
                road["roadId"],
                road["regionId"],
                road["name"],
                road["roadType"],
                road["directionMode"],
                road["lengthMeters"],
                _json_dumps(road["coordinates"], nullable=True),
                road["status"],
                _json_dumps(road["metadata"]),
                road["sourceType"],
                road["sourceReference"],
                road["verifiedAt"],
                road["verificationStatus"],
                now,
                now,
            ),
        )
        return 0 if existed else 1

    def _upsert_road_alias(
        self,
        conn: sqlite3.Connection,
        road: Dict[str, Any],
        alias: Dict[str, str],
        now: str,
    ) -> int:
        self._ensure_alias_owner_conn(
            conn,
            "road_aliases",
            "road_id",
            road["regionId"],
            alias["normalizedAlias"],
            road["roadId"],
            "roads.aliases",
        )
        existed = self._alias_exists_conn(
            conn,
            "road_aliases",
            road["regionId"],
            alias["alias"],
            "road_id",
            road["roadId"],
        )
        cursor = conn.execute(
            """
            INSERT INTO road_aliases (
                alias_id, region_id, road_id, alias, normalized_alias,
                source_type, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(region_id, road_id, alias) DO UPDATE SET
                source_type=excluded.source_type,
                status=excluded.status,
                updated_at=excluded.updated_at
            WHERE road_aliases.road_id = excluded.road_id
            """,
            (
                _stable_alias_id(
                    "road",
                    road["regionId"],
                    road["roadId"],
                    alias["normalizedAlias"],
                    alias["alias"],
                ),
                road["regionId"],
                road["roadId"],
                alias["alias"],
                alias["normalizedAlias"],
                road["sourceType"],
                road["status"],
                now,
                now,
            ),
        )
        if cursor.rowcount == 0:
            raise RegionalValidationError([
                validation_error(
                    "roads.aliases",
                    "same normalized alias points to a different road",
                    "alias_conflict",
                )
            ])
        return 0 if existed else 1

    def _upsert_intersection(self, conn: sqlite3.Connection, intersection: Dict[str, Any], now: str) -> int:
        existed = self._exists_conn(conn, "intersections", "intersection_id", intersection["intersectionId"])
        conn.execute(
            """
            INSERT INTO intersections (
                intersection_id, region_id, name, latitude, longitude,
                intersection_type, importance, status, metadata_json, source_type,
                source_reference, verified_at, verification_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(intersection_id) DO UPDATE SET
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                intersection_type=excluded.intersection_type,
                importance=excluded.importance,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                source_type=excluded.source_type,
                source_reference=excluded.source_reference,
                verified_at=excluded.verified_at,
                verification_status=excluded.verification_status,
                updated_at=excluded.updated_at
            """,
            (
                intersection["intersectionId"],
                intersection["regionId"],
                intersection["name"],
                intersection["latitude"],
                intersection["longitude"],
                intersection["intersectionType"],
                intersection["importance"],
                intersection["status"],
                _json_dumps(intersection["metadata"]),
                intersection["sourceType"],
                intersection["sourceReference"],
                intersection["verifiedAt"],
                intersection["verificationStatus"],
                now,
                now,
            ),
        )
        return 0 if existed else 1

    def _upsert_intersection_alias(
        self,
        conn: sqlite3.Connection,
        intersection: Dict[str, Any],
        alias: Dict[str, str],
        now: str,
    ) -> int:
        self._ensure_alias_owner_conn(
            conn,
            "intersection_aliases",
            "intersection_id",
            intersection["regionId"],
            alias["normalizedAlias"],
            intersection["intersectionId"],
            "intersections.aliases",
        )
        existed = self._alias_exists_conn(
            conn,
            "intersection_aliases",
            intersection["regionId"],
            alias["alias"],
            "intersection_id",
            intersection["intersectionId"],
        )
        cursor = conn.execute(
            """
            INSERT INTO intersection_aliases (
                alias_id, region_id, intersection_id, alias, normalized_alias,
                source_type, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(region_id, intersection_id, alias) DO UPDATE SET
                source_type=excluded.source_type,
                status=excluded.status,
                updated_at=excluded.updated_at
            WHERE intersection_aliases.intersection_id = excluded.intersection_id
            """,
            (
                _stable_alias_id(
                    "intersection",
                    intersection["regionId"],
                    intersection["intersectionId"],
                    alias["normalizedAlias"],
                    alias["alias"],
                ),
                intersection["regionId"],
                intersection["intersectionId"],
                alias["alias"],
                alias["normalizedAlias"],
                intersection["sourceType"],
                intersection["status"],
                now,
                now,
            ),
        )
        if cursor.rowcount == 0:
            raise RegionalValidationError([
                validation_error(
                    "intersections.aliases",
                    "same normalized alias points to a different intersection",
                    "alias_conflict",
                )
            ])
        return 0 if existed else 1

    def _upsert_relation(self, conn: sqlite3.Connection, relation: Dict[str, Any], now: str) -> int:
        existed = self._exists_conn(conn, "road_relations", "relation_id", relation["relationId"])
        conn.execute(
            """
            INSERT INTO road_relations (
                relation_id, region_id, from_entity_type, from_entity_id,
                to_entity_type, to_entity_id, relation_type, direction,
                distance_meters, metadata_json, status, source_type,
                source_reference, verified_at, verification_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relation_id) DO UPDATE SET
                direction=excluded.direction,
                distance_meters=excluded.distance_meters,
                metadata_json=excluded.metadata_json,
                status=excluded.status,
                source_type=excluded.source_type,
                source_reference=excluded.source_reference,
                verified_at=excluded.verified_at,
                verification_status=excluded.verification_status,
                updated_at=excluded.updated_at
            """,
            (
                relation["relationId"],
                relation["regionId"],
                relation["fromEntityType"],
                relation["fromEntityId"],
                relation["toEntityType"],
                relation["toEntityId"],
                relation["relationType"],
                relation["direction"],
                relation["distanceMeters"],
                _json_dumps(relation["metadata"]),
                relation["status"],
                relation["sourceType"],
                relation["sourceReference"],
                relation["verifiedAt"],
                relation["verificationStatus"],
                now,
                now,
            ),
        )
        return 0 if existed else 1

    def _upsert_poi(self, conn: sqlite3.Connection, poi: Dict[str, Any], now: str) -> int:
        existed = self._exists_conn(conn, "pois", "poi_id", poi["poiId"])
        conn.execute(
            """
            INSERT INTO pois (
                poi_id, region_id, name, type, road_id, intersection_id,
                latitude, longitude, importance, active_hours_json, metadata_json,
                status, source_type, source_reference, verified_at, verification_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(poi_id) DO UPDATE SET
                road_id=excluded.road_id,
                intersection_id=excluded.intersection_id,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                importance=excluded.importance,
                active_hours_json=excluded.active_hours_json,
                metadata_json=excluded.metadata_json,
                status=excluded.status,
                source_type=excluded.source_type,
                source_reference=excluded.source_reference,
                verified_at=excluded.verified_at,
                verification_status=excluded.verification_status,
                updated_at=excluded.updated_at
            """,
            (
                poi["poiId"],
                poi["regionId"],
                poi["name"],
                poi["type"],
                poi["roadId"],
                poi["intersectionId"],
                poi["latitude"],
                poi["longitude"],
                poi["importance"],
                _json_dumps(poi["activeHours"], nullable=True),
                _json_dumps(poi["metadata"]),
                poi["status"],
                poi["sourceType"],
                poi["sourceReference"],
                poi["verifiedAt"],
                poi["verificationStatus"],
                now,
                now,
            ),
        )
        return 0 if existed else 1

    def _exists_conn(self, conn: sqlite3.Connection, table: str, id_column: str, entity_id: str) -> bool:
        return conn.execute(
            f"SELECT 1 FROM {table} WHERE {id_column} = ?",
            (entity_id,),
        ).fetchone() is not None

    def _alias_exists_conn(
        self,
        conn: sqlite3.Connection,
        table: str,
        region_id: str,
        alias: str,
        entity_column: str,
        entity_id: str,
    ) -> bool:
        return conn.execute(
            f"SELECT 1 FROM {table} WHERE region_id = ? AND alias = ? AND {entity_column} = ?",
            (region_id, alias, entity_id),
        ).fetchone() is not None

    def _ensure_alias_owner_conn(
        self,
        conn: sqlite3.Connection,
        table: str,
        entity_column: str,
        region_id: str,
        normalized_alias: str,
        entity_id: str,
        path: str,
    ) -> None:
        row = conn.execute(
            f"""
            SELECT {entity_column} AS owner_id
            FROM {table}
            WHERE region_id = ? AND normalized_alias = ? AND {entity_column} <> ?
            LIMIT 1
            """,
            (region_id, normalized_alias, entity_id),
        ).fetchone()
        if row:
            raise RegionalValidationError([
                validation_error(
                    path,
                    "same normalized alias points to a different entity",
                    "alias_conflict",
                )
            ])

    def _validate_binding_entities_conn(
        self,
        conn: sqlite3.Connection,
        region_id: str,
        road_id: Optional[str],
        intersection_id: Optional[str],
    ) -> None:
        errors: List[Dict[str, str]] = []
        if conn.execute("SELECT 1 FROM regions WHERE region_id = ?", (region_id,)).fetchone() is None:
            errors.append(validation_error("regionId", "region does not exist", "dangling_reference"))
        if road_id:
            road = conn.execute(
                "SELECT region_id FROM roads WHERE road_id = ?",
                (road_id,),
            ).fetchone()
            if road is None:
                errors.append(validation_error("roadId", "road does not exist", "dangling_reference"))
            elif road["region_id"] != region_id:
                errors.append(validation_error("roadId", "road belongs to another region", "cross_region"))
        if intersection_id:
            intersection = conn.execute(
                "SELECT region_id FROM intersections WHERE intersection_id = ?",
                (intersection_id,),
            ).fetchone()
            if intersection is None:
                errors.append(
                    validation_error("intersectionId", "intersection does not exist", "dangling_reference")
                )
            elif intersection["region_id"] != region_id:
                errors.append(
                    validation_error(
                        "intersectionId",
                        "intersection belongs to another region",
                        "cross_region",
                    )
                )
        if errors:
            raise RegionalValidationError(errors)

    def _next_binding_id_conn(self, conn: sqlite3.Connection, event_id: str) -> str:
        import hashlib

        row = conn.execute(
            "SELECT COUNT(*) AS c FROM event_location_bindings WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        sequence = int(row["c"] or 0) + 1
        event_hash = hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:12]
        return f"elbind_{event_hash}_{sequence:04d}"

    def _find_alias_conflict(
        self,
        table: str,
        region_id: str,
        normalized_alias: str,
        entity_id: str,
        entity_column: str,
    ) -> Optional[sqlite3.Row]:
        conn = self._conn()
        try:
            return conn.execute(
                f"""
                SELECT * FROM {table}
                WHERE region_id = ? AND normalized_alias = ? AND {entity_column} <> ?
                LIMIT 1
                """,
                (region_id, normalized_alias, entity_id),
            ).fetchone()
        finally:
            conn.close()

    def _get_relation(self, relation_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM road_relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
            return self._relation_dict(row) if row else None
        finally:
            conn.close()

    def _get_poi(self, poi_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM pois WHERE poi_id = ?", (poi_id,)).fetchone()
            return self._poi_dict(row) if row else None
        finally:
            conn.close()

    # ── Row mapping ───────────────────────────────────────────────────────

    def _region_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "regionId": row["region_id"],
            "name": row["name"],
            "city": row["city"],
            "district": row["district"],
            "timezone": row["timezone"],
            "status": row["status"],
            "description": row["description"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "sourceType": row["source_type"],
            "sourceReference": row["source_reference"],
            "verifiedAt": row["verified_at"],
            "verificationStatus": row["verification_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _road_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "roadId": row["road_id"],
            "regionId": row["region_id"],
            "name": row["name"],
            "roadType": row["road_type"],
            "directionMode": row["direction_mode"],
            "lengthMeters": row["length_meters"],
            "coordinates": _json_loads(row["coordinates_json"], None),
            "status": row["status"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "sourceType": row["source_type"],
            "sourceReference": row["source_reference"],
            "verifiedAt": row["verified_at"],
            "verificationStatus": row["verification_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _intersection_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "intersectionId": row["intersection_id"],
            "regionId": row["region_id"],
            "name": row["name"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "intersectionType": row["intersection_type"],
            "importance": row["importance"],
            "status": row["status"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "sourceType": row["source_type"],
            "sourceReference": row["source_reference"],
            "verifiedAt": row["verified_at"],
            "verificationStatus": row["verification_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _relation_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "relationId": row["relation_id"],
            "regionId": row["region_id"],
            "fromEntityType": row["from_entity_type"],
            "fromEntityId": row["from_entity_id"],
            "toEntityType": row["to_entity_type"],
            "toEntityId": row["to_entity_id"],
            "relationType": row["relation_type"],
            "direction": row["direction"],
            "distanceMeters": row["distance_meters"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "status": row["status"],
            "sourceType": row["source_type"],
            "sourceReference": row["source_reference"],
            "verifiedAt": row["verified_at"],
            "verificationStatus": row["verification_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _poi_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "poiId": row["poi_id"],
            "regionId": row["region_id"],
            "name": row["name"],
            "type": row["type"],
            "roadId": row["road_id"],
            "intersectionId": row["intersection_id"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "importance": row["importance"],
            "activeHours": _json_loads(row["active_hours_json"], None),
            "metadata": _json_loads(row["metadata_json"], {}),
            "status": row["status"],
            "sourceType": row["source_type"],
            "sourceReference": row["source_reference"],
            "verifiedAt": row["verified_at"],
            "verificationStatus": row["verification_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _binding_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "bindingId": row["binding_id"],
            "eventId": row["event_id"],
            "regionId": row["region_id"],
            "roadId": row["road_id"],
            "intersectionId": row["intersection_id"],
            "resolutionMethod": row["resolution_method"],
            "matchedAlias": row["matched_alias"],
            "status": row["status"],
            "resolvedAt": row["resolved_at"],
            "sourceType": row["source_type"],
            "sourceReference": row["source_reference"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
