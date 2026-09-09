"""Deterministic event location resolution and binding service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.regional.repository import RegionalValidationError, SQLiteRegionalRepository
from backend.tools.event_identity import (
    EventIdentityError,
    compact_event_context,
    extract_event_id,
    hydrate_authoritative_event,
)


class LocationResolutionError(ValueError):
    """Raised when event or region scope cannot be resolved honestly."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _candidate(kind: str, item: Dict[str, Any], method: str) -> Dict[str, Any]:
    result = {
        "entityType": kind,
        "regionId": item["regionId"],
        "matchedAlias": item["matchedAlias"],
        "normalizedAlias": item["normalizedAlias"],
        "name": item["name"],
        "candidateMethod": method,
    }
    if kind == "intersection":
        result["intersectionId"] = item["intersectionId"]
    else:
        result["roadId"] = item["roadId"]
    return result


def _dedupe_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for candidate in candidates:
        key = (
            candidate.get("entityType"),
            candidate.get("regionId"),
            candidate.get("roadId"),
            candidate.get("intersectionId"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


class EventLocationResolver:
    """Resolve event roadName to canonical regional identity without fuzzy search."""

    def __init__(self, repository: Optional[SQLiteRegionalRepository] = None):
        self.repository = repository or SQLiteRegionalRepository()

    def resolve(
        self,
        event_snapshot: Dict[str, Any],
        *,
        region_id: str = "",
    ) -> Dict[str, Any]:
        scoped_region = str(region_id or "").strip()
        if scoped_region and self.repository.get_region(scoped_region) is None:
            raise LocationResolutionError("region_not_found", f"Region '{scoped_region}' not found")

        event_id = extract_event_id(event_snapshot)
        event = compact_event_context(event_snapshot)
        road_name = str(event.get("roadName") or "").strip()
        base = {
            "eventId": event_id,
            "inputRoadName": road_name,
            "inputDirection": event.get("direction") or "",
            "nearbySchool": bool(event.get("nearbySchool")),
            "nearbyHospital": bool(event.get("nearbyHospital")),
            "regionScope": scoped_region,
        }
        if not road_name:
            return {
                **base,
                "status": "unresolved",
                "resolutionMethod": "UNRESOLVED",
                "regionId": None,
                "roadId": None,
                "intersectionId": None,
                "matchedAlias": None,
                "candidates": [],
            }

        ordered_attempts = [
            (
                "intersection",
                "EXACT_INTERSECTION_ALIAS",
                self.repository.find_intersection_alias_matches,
                False,
            ),
            (
                "intersection",
                "NORMALIZED_NAME_MATCH",
                self.repository.find_intersection_alias_matches,
                True,
            ),
            ("road", "EXACT_ROAD_ALIAS", self.repository.find_road_alias_matches, False),
            ("road", "NORMALIZED_NAME_MATCH", self.repository.find_road_alias_matches, True),
        ]

        for kind, method, finder, normalized in ordered_attempts:
            raw_candidates = finder(road_name, region_id=scoped_region, normalized=normalized)
            candidates = _dedupe_candidates([
                _candidate(kind, item, method) for item in raw_candidates
            ])
            if len(candidates) == 1:
                candidate = candidates[0]
                return {
                    **base,
                    "status": "resolved",
                    "resolutionMethod": method,
                    "regionId": candidate["regionId"],
                    "roadId": candidate.get("roadId"),
                    "intersectionId": candidate.get("intersectionId"),
                    "matchedAlias": candidate["matchedAlias"],
                    "candidates": candidates,
                }
            if len(candidates) > 1:
                return {
                    **base,
                    "status": "ambiguous",
                    "resolutionMethod": "AMBIGUOUS",
                    "regionId": None,
                    "roadId": None,
                    "intersectionId": None,
                    "matchedAlias": None,
                    "candidates": candidates,
                }

        return {
            **base,
            "status": "unresolved",
            "resolutionMethod": "UNRESOLVED",
            "regionId": None,
            "roadId": None,
            "intersectionId": None,
            "matchedAlias": None,
            "candidates": [],
        }


class EventLocationBindingService:
    """Preview and persist event location bindings from authoritative events."""

    def __init__(self, repository: Optional[SQLiteRegionalRepository] = None):
        self.repository = repository or SQLiteRegionalRepository()
        self.resolver = EventLocationResolver(self.repository)

    def preview(
        self,
        event_id: str,
        *,
        region_id: str = "",
        client_event: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            snapshot = hydrate_authoritative_event(event_id, client_event=client_event)
        except EventIdentityError as err:
            raise LocationResolutionError(err.code, err.message)
        return self.resolver.resolve(snapshot, region_id=region_id)

    def resolve_and_bind(
        self,
        event_id: str,
        *,
        region_id: str = "",
        client_event: Optional[Dict[str, Any]] = None,
        re_resolve: bool = False,
    ) -> Dict[str, Any]:
        resolution = self.preview(event_id, region_id=region_id, client_event=client_event)
        if resolution["status"] != "resolved":
            return {
                "resolution": resolution,
                "binding": None,
                "locationContext": None,
            }
        binding = self.repository.save_resolved_event_location_binding(
            resolution,
            re_resolve=re_resolve,
        )
        return {
            "resolution": resolution,
            "binding": binding,
            "locationContext": self.repository.build_regional_location_context(binding),
        }

    def get_binding_context(self, event_id: str) -> Optional[Dict[str, Any]]:
        binding = self.repository.get_active_event_location_binding(event_id)
        if not binding:
            return None
        return {
            "binding": binding,
            "locationContext": self.repository.build_regional_location_context(binding),
            "history": self.repository.list_event_location_bindings(event_id),
        }
