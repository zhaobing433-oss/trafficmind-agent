"""Regional Core API — Phase21 Wave A.

Read APIs expose imported regional context. The only write surface is the
deterministic Context Pack import endpoint; no CRUD admin UI is introduced.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.regional.historical import HistoricalTrafficService
from backend.regional.repository import RegionalValidationError, SQLiteRegionalRepository
from backend.regional.resolver import EventLocationBindingService, LocationResolutionError


router = APIRouter(prefix="/regional", tags=["Regional Core V1"])

_repo = SQLiteRegionalRepository()


def _get_location_service() -> EventLocationBindingService:
    return EventLocationBindingService(_repo)


def _get_historical_service() -> HistoricalTrafficService:
    return HistoricalTrafficService(_repo)


class ContextPackImportRequest(BaseModel):
    packageVersion: int
    region: Dict[str, Any]
    roads: list[Dict[str, Any]] = []
    intersections: list[Dict[str, Any]] = []
    roadRelations: list[Dict[str, Any]] = []
    relations: list[Dict[str, Any]] = []
    road_relations: list[Dict[str, Any]] = []
    pois: list[Dict[str, Any]] = []

    model_config = ConfigDict(extra="allow")


class EventLocationResolveRequest(BaseModel):
    regionId: Optional[str] = ""
    event: Optional[Dict[str, Any]] = None
    reResolve: bool = False

    model_config = ConfigDict(extra="allow")


def _not_found(name: str, entity_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": f"{name} '{entity_id}' not found"})


def _validation_http_error(err: RegionalValidationError) -> HTTPException:
    status = 409 if any(
        item.get("code") == "binding_changed_requires_reresolution"
        for item in err.errors
    ) else 400
    return HTTPException(
        status_code=status,
        detail={"code": "regional_validation_error", "errors": err.errors},
    )


def _resolution_http_error(err: LocationResolutionError) -> HTTPException:
    status = 404 if err.code in {"event_not_found", "region_not_found"} else 400
    return HTTPException(status_code=status, detail={"code": err.code, "message": err.message})


@router.post("/context-packs/import", summary="Import deterministic pilot region context pack")
async def import_region_context_pack(body: ContextPackImportRequest):
    payload = body.model_dump()
    if not payload.get("roadRelations"):
        payload["roadRelations"] = payload.get("relations") or payload.get("road_relations") or []
    try:
        return _repo.import_context_pack(payload)
    except RegionalValidationError as err:
        raise _validation_http_error(err)


@router.post("/events/{event_id}/location/preview", summary="Preview event location resolution")
async def preview_event_location(event_id: str, body: EventLocationResolveRequest):
    try:
        return _get_location_service().preview(
            event_id,
            region_id=body.regionId or "",
            client_event=body.event,
        )
    except LocationResolutionError as err:
        raise _resolution_http_error(err)


@router.post("/events/{event_id}/location/resolve", summary="Resolve and persist event location binding")
async def resolve_event_location(event_id: str, body: EventLocationResolveRequest):
    try:
        return _get_location_service().resolve_and_bind(
            event_id,
            region_id=body.regionId or "",
            client_event=body.event,
            re_resolve=body.reResolve,
        )
    except LocationResolutionError as err:
        raise _resolution_http_error(err)
    except RegionalValidationError as err:
        raise _validation_http_error(err)


@router.get("/events/{event_id}/location-binding", summary="Get active event location binding")
async def get_event_location_binding(event_id: str):
    result = _get_location_service().get_binding_context(event_id)
    if not result:
        raise _not_found("Event location binding", event_id)
    return result


@router.get("/events/{event_id}/history", summary="Get canonical historical traffic context for event")
async def get_event_historical_context(
    event_id: str,
    windowDays: int = Query(30, ge=1, le=365, description="Historical lookback window in days"),
):
    try:
        return _get_historical_service().get_historical_context_for_event(
            event_id,
            window_days=windowDays,
        )
    except LocationResolutionError as err:
        raise _resolution_http_error(err)


@router.get("/regions", summary="List pilot regions")
async def list_regions():
    regions = _repo.list_regions()
    return {"total": len(regions), "regions": regions}


@router.get("/regions/{region_id}", summary="Get pilot region")
async def get_region(region_id: str):
    region = _repo.get_region(region_id)
    if not region:
        raise _not_found("Region", region_id)
    return region


@router.get("/regions/{region_id}/summary", summary="Get regional context summary")
async def get_region_summary(region_id: str):
    summary = _repo.get_region_summary(region_id)
    if not summary:
        raise _not_found("Region", region_id)
    return summary


@router.get("/regions/{region_id}/roads", summary="List roads in region")
async def list_region_roads(region_id: str):
    if not _repo.get_region(region_id):
        raise _not_found("Region", region_id)
    roads = _repo.list_roads(region_id)
    return {"total": len(roads), "roads": roads}


@router.get("/roads/{road_id}", summary="Get road")
async def get_road(road_id: str):
    road = _repo.get_road(road_id)
    if not road:
        raise _not_found("Road", road_id)
    return road


@router.get("/regions/{region_id}/intersections", summary="List intersections in region")
async def list_region_intersections(region_id: str):
    if not _repo.get_region(region_id):
        raise _not_found("Region", region_id)
    intersections = _repo.list_intersections(region_id)
    return {"total": len(intersections), "intersections": intersections}


@router.get("/intersections/{intersection_id}", summary="Get intersection")
async def get_intersection(intersection_id: str):
    intersection = _repo.get_intersection(intersection_id)
    if not intersection:
        raise _not_found("Intersection", intersection_id)
    return intersection


@router.get("/regions/{region_id}/relations", summary="List road relations in region")
async def list_region_relations(
    region_id: str,
    entityType: str = Query("", description="road or intersection"),
    entityId: str = Query("", description="Entity ID"),
    relationType: str = Query("", description="connects/upstream/downstream/adjacent/alternate"),
):
    if not _repo.get_region(region_id):
        raise _not_found("Region", region_id)
    relations = _repo.list_relations(
        region_id,
        entity_type=entityType,
        entity_id=entityId,
        relation_type=relationType,
    )
    return {"total": len(relations), "relations": relations}


@router.get("/intersections/{intersection_id}/roads", summary="List roads connected to intersection")
async def list_connected_roads(intersection_id: str):
    roads = _repo.list_connected_roads_for_intersection(intersection_id)
    return {"total": len(roads), "roads": roads}


@router.get("/roads/{road_id}/intersections", summary="List intersections connected to road")
async def list_road_intersections(road_id: str):
    intersections = _repo.list_intersections_for_road(road_id)
    return {"total": len(intersections), "intersections": intersections}


@router.get("/regions/{region_id}/pois", summary="List POIs in region")
async def list_region_pois(
    region_id: str,
    type: Optional[str] = Query(None, description="Optional POI type filter"),
):
    if not _repo.get_region(region_id):
        raise _not_found("Region", region_id)
    pois = _repo.list_pois(region_id)
    if type:
        pois = [poi for poi in pois if poi["type"] == type]
    return {"total": len(pois), "pois": pois}
