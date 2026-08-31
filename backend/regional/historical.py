"""Canonical historical traffic context for Phase21 regional bindings."""

from __future__ import annotations

import math
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import backend.config as _config
from backend.regional.repository import SQLiteRegionalRepository
from backend.regional.resolver import LocationResolutionError
from backend.tools.alert_tools import UNCLOSED_STATUSES
from backend.tools.event_identity import (
    EventIdentityError,
    extract_event_id,
    hydrate_authoritative_event,
)


class HistoricalWindow(TypedDict):
    start: str
    end: str
    asOf: str
    days: int


class HistoricalEventRef(TypedDict):
    eventId: str
    eventType: str
    createdAt: str
    riskLevel: str
    status: str


class HistoricalProvenance(TypedDict, total=False):
    sourceType: str
    bindingSource: str
    capturedAt: str
    asOf: str
    windowStart: str
    windowEnd: str
    bindingId: str
    regionId: str
    roadId: Optional[str]
    intersectionId: Optional[str]
    queryModel: str


class HistoricalTrafficContext(TypedDict, total=False):
    status: str
    reason: str
    eventId: str
    regionId: Optional[str]
    roadId: Optional[str]
    intersectionId: Optional[str]
    locationGranularity: str
    window: HistoricalWindow
    eventCount: int
    eventTypeDistribution: Dict[str, int]
    riskDistribution: Dict[str, int]
    averageDuration: Optional[float]
    durationSampleCount: int
    maxRisk: Optional[float]
    unclosedCount: int
    timeOfDayDistribution: Dict[str, int]
    recentEventRefs: List[HistoricalEventRef]
    connectedRoadIds: List[str]
    provenance: HistoricalProvenance


TIME_OF_DAY_BUCKETS = ("00-06", "06-12", "12-18", "18-24")
DEFAULT_WINDOW_DAYS = 30
MAX_RECENT_EVENT_REFS = 5


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: Any, tz: ZoneInfo) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _iso_local(value: datetime) -> str:
    return value.isoformat()


def _time_bucket(value: datetime) -> str:
    hour = value.hour
    if hour < 6:
        return "00-06"
    if hour < 12:
        return "06-12"
    if hour < 18:
        return "12-18"
    return "18-24"


def _finite_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _event_type_key(value: Any) -> str:
    text = str(value or "").strip()
    return text or "UNKNOWN"


def _risk_key(value: Any) -> str:
    text = str(value or "").strip()
    return text or "UNKNOWN"


class HistoricalTrafficService:
    """Build deterministic history using active canonical location bindings."""

    def __init__(self, repository: Optional[SQLiteRegionalRepository] = None):
        self.repository = repository or SQLiteRegionalRepository()

    def get_historical_context(
        self,
        *,
        region_id: str,
        start_time: Any,
        end_time: Any,
        road_id: Optional[str] = None,
        intersection_id: Optional[str] = None,
        exclude_event_id: Optional[str] = None,
    ) -> HistoricalTrafficContext:
        region = self.repository.get_region(region_id)
        if region is None:
            return self._unavailable_context("", "REGION_NOT_FOUND", 1)
        tz = self._region_timezone(region)
        if tz is None:
            return self._unavailable_context("", "INVALID_REGION_TIMEZONE", 1)
        start = _parse_timestamp(start_time, tz)
        end = _parse_timestamp(end_time, tz)
        days = 1
        if start is not None and end is not None and end > start:
            days = max(1, (end - start).days)
        if start is None or end is None or end <= start:
            return self._unavailable_context("", "INVALID_TIME_WINDOW", days)

        road = self.repository.get_road(road_id) if road_id else None
        intersection = self.repository.get_intersection(intersection_id) if intersection_id else None
        if intersection_id:
            if not intersection or intersection["regionId"] != region_id:
                return self._unavailable_context("", "LOCATION_NOT_RESOLVED", days)
            granularity = "intersection"
        elif road_id:
            if not road or road["regionId"] != region_id:
                return self._unavailable_context("", "LOCATION_NOT_RESOLVED", days)
            granularity = "road"
        else:
            return self._unavailable_context("", "LOCATION_GRANULARITY_UNSUPPORTED", days)

        excluded = str(exclude_event_id or "").strip()
        records = self._query_bound_records(
            region_id=region_id,
            road_id=road_id,
            intersection_id=intersection_id,
            granularity=granularity,
        )
        scoped_records = []
        for record in records:
            if excluded and str(record.get("eventId") or "").strip() == excluded:
                continue
            created_at = _parse_timestamp(record.get("createdAt"), tz)
            if created_at is None:
                continue
            if start <= created_at < end:
                scoped_records.append({**record, "_createdAtParsed": created_at})

        scoped_records.sort(
            key=lambda item: (
                item["_createdAtParsed"],
                str(item.get("eventId") or ""),
            ),
            reverse=True,
        )
        binding = {
            "bindingId": "",
            "regionId": region_id,
            "roadId": road_id,
            "intersectionId": intersection_id,
        }
        return self._build_ready_context(
            event_id=excluded,
            binding=binding,
            granularity=granularity,
            days=days,
            as_of=end,
            window_start=start,
            records=scoped_records,
        )

    def get_historical_context_for_event(
        self,
        event_id: str,
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> HistoricalTrafficContext:
        days = self._validate_window_days(window_days)
        try:
            authoritative_event = hydrate_authoritative_event(event_id)
        except EventIdentityError as err:
            raise LocationResolutionError(err.code, err.message)

        canonical_event_id = extract_event_id(authoritative_event)
        binding = self.repository.get_active_event_location_binding(canonical_event_id)
        if not binding:
            return self._unavailable_context(
                canonical_event_id,
                "LOCATION_NOT_RESOLVED",
                days,
            )

        region = self.repository.get_region(binding["regionId"])
        if region is None:
            return self._unavailable_context(
                canonical_event_id,
                "REGION_NOT_FOUND",
                days,
                binding=binding,
            )
        tz = self._region_timezone(region)
        if tz is None:
            return self._unavailable_context(
                canonical_event_id,
                "INVALID_REGION_TIMEZONE",
                days,
                binding=binding,
            )
        as_of = _parse_timestamp(authoritative_event.get("createdAt"), tz)
        if as_of is None:
            return self._unavailable_context(
                canonical_event_id,
                "INVALID_EVENT_TIMESTAMP",
                days,
                binding=binding,
            )

        road_id = binding.get("roadId")
        intersection_id = binding.get("intersectionId")
        if intersection_id:
            granularity = "intersection"
        elif road_id:
            granularity = "road"
        else:
            return self._unavailable_context(
                canonical_event_id,
                "LOCATION_GRANULARITY_UNSUPPORTED",
                days,
                binding=binding,
            )

        window_start = as_of - timedelta(days=days)
        records = self._query_bound_records(
            region_id=binding["regionId"],
            road_id=road_id,
            intersection_id=intersection_id,
            granularity=granularity,
        )
        previous_records = []
        for record in records:
            if str(record.get("eventId") or "").strip() == canonical_event_id:
                continue
            created_at = _parse_timestamp(record.get("createdAt"), tz)
            if created_at is None:
                continue
            if window_start <= created_at < as_of:
                previous_records.append({**record, "_createdAtParsed": created_at})

        previous_records.sort(
            key=lambda item: (
                item["_createdAtParsed"],
                str(item.get("eventId") or ""),
            ),
            reverse=True,
        )
        return self._build_ready_context(
            event_id=canonical_event_id,
            binding=binding,
            granularity=granularity,
            days=days,
            as_of=as_of,
            window_start=window_start,
            records=previous_records,
        )

    def _conn(self) -> sqlite3.Connection:
        path = self.repository.db_path or _config.DB_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def _query_bound_records(
        self,
        *,
        region_id: str,
        road_id: Optional[str],
        intersection_id: Optional[str],
        granularity: str,
    ) -> List[Dict[str, Any]]:
        if granularity == "intersection":
            location_clause = "b.intersection_id = ?"
            params: List[Any] = [region_id, intersection_id]
        else:
            location_clause = "b.road_id = ? AND b.intersection_id IS NULL"
            params = [region_id, road_id]
        conn = self._conn()
        try:
            rows = conn.execute(
                f"""
                SELECT
                    e.eventId,
                    e.eventType,
                    e.riskScore,
                    e.riskLevel,
                    e.status,
                    e.duration,
                    e.createdAt,
                    b.binding_id,
                    b.region_id,
                    b.road_id,
                    b.intersection_id
                FROM event_records e
                JOIN event_location_bindings b
                  ON b.event_id = e.eventId
                 AND b.status = 'resolved'
                WHERE b.region_id = ?
                  AND {location_clause}
                ORDER BY e.createdAt DESC, e.eventId DESC
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def _build_ready_context(
        self,
        *,
        event_id: str,
        binding: Dict[str, Any],
        granularity: str,
        days: int,
        as_of: datetime,
        window_start: datetime,
        records: List[Dict[str, Any]],
    ) -> HistoricalTrafficContext:
        event_type_counter: Counter[str] = Counter()
        risk_counter: Counter[str] = Counter()
        time_counter: Counter[str] = Counter({bucket: 0 for bucket in TIME_OF_DAY_BUCKETS})
        durations: List[float] = []
        max_risk: Optional[float] = None
        unclosed_count = 0

        for record in records:
            event_type_counter[_event_type_key(record.get("eventType"))] += 1
            risk_counter[_risk_key(record.get("riskLevel"))] += 1
            time_counter[_time_bucket(record["_createdAtParsed"])] += 1
            duration = _finite_float(record.get("duration"))
            if duration is not None:
                durations.append(duration)
            risk_score = _finite_float(record.get("riskScore"))
            if risk_score is not None:
                max_risk = risk_score if max_risk is None else max(max_risk, risk_score)
            if str(record.get("status") or "").strip() in UNCLOSED_STATUSES:
                unclosed_count += 1

        recent_refs: List[HistoricalEventRef] = [
            {
                "eventId": str(record.get("eventId") or ""),
                "eventType": _event_type_key(record.get("eventType")),
                "createdAt": str(record.get("createdAt") or ""),
                "riskLevel": _risk_key(record.get("riskLevel")),
                "status": str(record.get("status") or ""),
            }
            for record in records[:MAX_RECENT_EVENT_REFS]
        ]
        connected_road_ids = []
        if granularity == "intersection" and binding.get("intersectionId"):
            connected_road_ids = [
                road["roadId"]
                for road in self.repository.list_connected_roads_for_intersection(
                    binding["intersectionId"]
                )
            ]

        window_end = as_of
        return {
            "status": "READY",
            "eventId": event_id,
            "regionId": binding["regionId"],
            "roadId": binding.get("roadId"),
            "intersectionId": binding.get("intersectionId"),
            "locationGranularity": granularity,
            "window": {
                "start": _iso_local(window_start),
                "end": _iso_local(window_end),
                "asOf": _iso_local(as_of),
                "days": days,
            },
            "eventCount": len(records),
            "eventTypeDistribution": dict(sorted(event_type_counter.items())),
            "riskDistribution": dict(sorted(risk_counter.items())),
            "averageDuration": round(sum(durations) / len(durations), 2)
            if durations
            else None,
            "durationSampleCount": len(durations),
            "maxRisk": max_risk,
            "unclosedCount": unclosed_count,
            "timeOfDayDistribution": dict(time_counter),
            "recentEventRefs": recent_refs,
            "connectedRoadIds": connected_road_ids,
            "provenance": self._provenance(
                binding=binding,
                as_of=as_of,
                window_start=window_start,
                window_end=window_end,
            ),
        }

    def _unavailable_context(
        self,
        event_id: str,
        reason: str,
        days: int,
        *,
        binding: Optional[Dict[str, Any]] = None,
    ) -> HistoricalTrafficContext:
        now = _utc_now_iso()
        return {
            "status": "UNAVAILABLE",
            "reason": reason,
            "eventId": event_id,
            "regionId": binding.get("regionId") if binding else None,
            "roadId": binding.get("roadId") if binding else None,
            "intersectionId": binding.get("intersectionId") if binding else None,
            "locationGranularity": "unavailable",
            "window": {
                "start": "",
                "end": "",
                "asOf": "",
                "days": days,
            },
            "eventCount": 0,
            "eventTypeDistribution": {},
            "riskDistribution": {},
            "averageDuration": None,
            "durationSampleCount": 0,
            "maxRisk": None,
            "unclosedCount": 0,
            "timeOfDayDistribution": {bucket: 0 for bucket in TIME_OF_DAY_BUCKETS},
            "recentEventRefs": [],
            "connectedRoadIds": [],
            "provenance": {
                "sourceType": "event_records",
                "bindingSource": "event_location_bindings",
                "capturedAt": now,
                "asOf": "",
                "windowStart": "",
                "windowEnd": "",
                "bindingId": binding.get("bindingId") if binding else "",
                "regionId": binding.get("regionId") if binding else "",
                "roadId": binding.get("roadId") if binding else None,
                "intersectionId": binding.get("intersectionId") if binding else None,
                "queryModel": "active_resolved_event_location_binding",
            },
        }

    def _provenance(
        self,
        *,
        binding: Dict[str, Any],
        as_of: datetime,
        window_start: datetime,
        window_end: datetime,
    ) -> HistoricalProvenance:
        return {
            "sourceType": "event_records",
            "bindingSource": "event_location_bindings",
            "capturedAt": _utc_now_iso(),
            "asOf": _iso_local(as_of),
            "windowStart": _iso_local(window_start),
            "windowEnd": _iso_local(window_end),
            "bindingId": binding.get("bindingId", ""),
            "regionId": binding["regionId"],
            "roadId": binding.get("roadId"),
            "intersectionId": binding.get("intersectionId"),
            "queryModel": "active_resolved_event_location_binding",
        }

    def _region_timezone(self, region: Dict[str, Any]) -> Optional[ZoneInfo]:
        name = (region or {}).get("timezone") or "UTC"
        try:
            return ZoneInfo(str(name))
        except ZoneInfoNotFoundError:
            return None

    def _validate_window_days(self, value: int) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = DEFAULT_WINDOW_DAYS
        return min(max(days, 1), 365)
