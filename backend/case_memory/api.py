"""Traffic Case Memory API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.case_memory.models import CaseMemoryError
from backend.case_memory.service import TrafficCaseMemoryService


router = APIRouter(prefix="/case-memory", tags=["Traffic Case Memory"])


def _service() -> TrafficCaseMemoryService:
    return TrafficCaseMemoryService()


def _raise_http(exc: CaseMemoryError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("/from-workflow/{run_id}")
def build_case_from_workflow(
    run_id: str,
    rebuild: bool = Query(False),
):
    try:
        return _service().build_from_workflow_run(run_id, rebuild=rebuild).to_dict()
    except CaseMemoryError as exc:
        _raise_http(exc)


@router.get("")
def query_case_memories(
    regionId: str = Query(...),
    eventType: str = Query(...),
    roadId: Optional[str] = Query(None),
    intersectionId: Optional[str] = Query(None),
    finalStatus: Optional[str] = Query(None),
    qualityStatus: Optional[str] = Query(None),
    asOf: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=50),
    forAgent: bool = Query(False),
):
    try:
        result = _service().query_cases(
            region_id=regionId,
            event_type=eventType,
            road_id=roadId,
            intersection_id=intersectionId,
            final_status=finalStatus,
            quality_status=qualityStatus,
            as_of=asOf,
            limit=limit,
            for_agent=forAgent,
        )
        return {
            "cases": [case.to_dict() for case in result["cases"]],
            "total": result["total"],
            "limit": result["limit"],
        }
    except CaseMemoryError as exc:
        _raise_http(exc)


@router.get("/events/{event_id}")
def get_case_context_for_event(
    event_id: str,
    limit: int = Query(5, ge=1, le=20),
):
    try:
        return _service().get_case_context_for_event(event_id, limit=limit)
    except CaseMemoryError as exc:
        _raise_http(exc)


@router.get("/{case_id}")
def get_case_memory(case_id: str):
    try:
        return _service().get_case(case_id).to_dict()
    except CaseMemoryError as exc:
        _raise_http(exc)
