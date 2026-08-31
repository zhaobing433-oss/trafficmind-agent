"""Traffic case memory service layer."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from backend.case_memory.builder import TrafficCaseBuilder, _compact_event_snapshot
from backend.case_memory.models import CaseBuildResult, CaseMemoryError, TrafficCaseMemory
from backend.case_memory.repository import SQLiteCaseMemoryRepository
from backend.regional.repository import SQLiteRegionalRepository
from backend.tools.db_tools import get_event_by_id


class TrafficCaseMemoryService:
    def __init__(
        self,
        *,
        repository: Optional[SQLiteCaseMemoryRepository] = None,
        builder: Optional[TrafficCaseBuilder] = None,
        regional_repo: Optional[SQLiteRegionalRepository] = None,
    ):
        self.repository = repository or SQLiteCaseMemoryRepository()
        self.regional_repo = regional_repo or SQLiteRegionalRepository()
        self.builder = builder or TrafficCaseBuilder(regional_repo=self.regional_repo)

    def build_from_workflow_run(self, run_id: str, *, rebuild: bool = False) -> CaseBuildResult:
        existing = self.repository.get_case_by_source_workflow_run_id(run_id)
        if existing and not rebuild:
            return CaseBuildResult(case=existing, created=False, rebuilt=False)
        built = self.builder.build_from_workflow_run(run_id)
        if existing:
            case = self.repository.update_case_preserving_identity(existing, built)
            return CaseBuildResult(case=case, created=False, rebuilt=True)
        try:
            case = self.repository.insert_case(built)
            return CaseBuildResult(case=case, created=True, rebuilt=False)
        except sqlite3.IntegrityError:
            existing_after_race = self.repository.get_case_by_source_workflow_run_id(run_id)
            if existing_after_race:
                return CaseBuildResult(case=existing_after_race, created=False, rebuilt=False)
            raise

    def get_case(self, case_id: str) -> TrafficCaseMemory:
        case = self.repository.get_case(case_id)
        if not case:
            raise CaseMemoryError("CASE_NOT_FOUND", f"case not found: {case_id}", status_code=404)
        return case

    def query_cases(
        self,
        *,
        region_id: str,
        event_type: str,
        road_id: Optional[str] = None,
        intersection_id: Optional[str] = None,
        final_status: Optional[str] = None,
        quality_status: Optional[str] = None,
        as_of: Optional[str] = None,
        limit: int = 5,
        for_agent: bool = False,
    ) -> Dict[str, Any]:
        if not region_id:
            raise CaseMemoryError("REGION_ID_REQUIRED", "regionId is required", status_code=422)
        if not event_type:
            raise CaseMemoryError("EVENT_TYPE_REQUIRED", "eventType is required", status_code=422)
        return self.repository.query_cases(
            region_id=region_id,
            event_type=event_type,
            road_id=road_id,
            intersection_id=intersection_id,
            final_status=final_status,
            quality_status=quality_status,
            as_of=as_of,
            limit=limit,
            for_agent=for_agent,
        )

    def get_case_context_for_event(self, event_id: str, *, limit: int = 5) -> Dict[str, Any]:
        event = get_event_by_id(event_id)
        if not event:
            raise CaseMemoryError("EVENT_NOT_FOUND", f"event not found: {event_id}", status_code=404)
        binding = self.regional_repo.get_active_event_location_binding(event_id)
        if not binding or not binding.get("regionId"):
            raise CaseMemoryError(
                "EVENT_CANONICAL_REGION_MISSING",
                "case context requires a resolved canonical event location",
                status_code=409,
            )
        snapshot = _compact_event_snapshot(event)
        event_type = str(snapshot.get("eventType") or "").strip()
        if not event_type:
            raise CaseMemoryError(
                "EVENT_TYPE_REQUIRED",
                "eventType is required for case context retrieval",
                status_code=422,
            )
        as_of = snapshot.get("createdAt")
        result = self.repository.find_context_candidates(
            region_id=str(binding["regionId"]),
            event_type=event_type,
            road_id=binding.get("roadId"),
            intersection_id=binding.get("intersectionId"),
            as_of=as_of,
            limit=limit,
        )
        return {
            "eventId": event_id,
            "regionId": binding["regionId"],
            "eventType": event_type,
            "asOf": as_of,
            "location": {
                "roadId": binding.get("roadId"),
                "intersectionId": binding.get("intersectionId"),
            },
            "cases": [case.to_dict() for case in result["cases"]],
            "total": result["total"],
            "limit": result["limit"],
            "retrievalPolicy": {
                "crossRegionBlocked": True,
                "futureCaseLeakageBlocked": True,
                "roadNameUsedAsIdentity": False,
                "qualityStatuses": ["validated", "partial"],
            },
        }
