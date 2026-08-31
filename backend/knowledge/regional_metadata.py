"""Phase21 Knowledge regional applicability metadata helpers.

The RAG SQLite document remains the source of truth. These helpers normalize
user/API metadata into canonical fields before chunking/indexing, and keep
legacy unscoped knowledge distinct from explicitly global knowledge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.regional.repository import SQLiteRegionalRepository


GROUNDING_SCOPE_GLOBAL = "GLOBAL"
GROUNDING_SCOPE_REGIONAL = "REGIONAL"
GROUNDING_SCOPE_LEGACY_UNSCOPED = "LEGACY_UNSCOPED"
GENERIC_EVENT_TYPES = {"*", "all", "any", "generic", "通用", "全部", "不限"}


class KnowledgeMetadataError(ValueError):
    """Raised when Knowledge regional metadata is inconsistent."""


def _first_present(metadata: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in metadata:
            value = metadata.get(key)
            if value is not None and value != "":
                return value
    return None


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_effective_datetime(value: Any, field_name: str) -> Optional[datetime]:
    """Parse optional effective time as UTC-aware datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise KnowledgeMetadataError(f"{field_name} 不是有效 ISO 时间") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_event_type(value: Any) -> Optional[str]:
    text = _clean_text(value)
    return text.lower() if text else None


def event_type_applicable(document_event_type: Optional[str], target_event_type: Optional[str]) -> bool:
    """Canonical event type matching. Null/generic document type is reusable."""
    doc_type = normalize_event_type(document_event_type)
    if not doc_type or doc_type.lower() in GENERIC_EVENT_TYPES:
        return True
    target = normalize_event_type(target_event_type)
    return bool(target) and doc_type == target


def _normalize_scope(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    upper = text.upper()
    aliases = {
        "GLOBAL": GROUNDING_SCOPE_GLOBAL,
        "REGIONAL": GROUNDING_SCOPE_REGIONAL,
        "REGION": GROUNDING_SCOPE_REGIONAL,
        "LEGACY_UNSCOPED": GROUNDING_SCOPE_LEGACY_UNSCOPED,
        "UNSCOPED": GROUNDING_SCOPE_LEGACY_UNSCOPED,
    }
    scope = aliases.get(upper)
    if not scope:
        raise KnowledgeMetadataError(f"groundingScope 不支持: {text}")
    return scope


def normalize_knowledge_metadata(
    metadata: Optional[Dict[str, Any]],
    *,
    regional_repository: Optional[SQLiteRegionalRepository] = None,
    validate_refs: bool = True,
) -> Dict[str, Any]:
    """Normalize API metadata to RagDocument fields.

    Canonical fields accept camelCase and snake_case. roadId/intersectionId are
    only accepted with explicit regionId to avoid dual-truth inference.
    """
    meta = metadata or {}
    if not isinstance(meta, dict):
        raise KnowledgeMetadataError("metadata 必须是 JSON 对象")

    region_id = _clean_text(_first_present(meta, "regionId", "region_id"))
    road_id = _clean_text(_first_present(meta, "roadId", "road_id"))
    intersection_id = _clean_text(_first_present(meta, "intersectionId", "intersection_id"))
    explicit_scope = _normalize_scope(_first_present(meta, "groundingScope", "grounding_scope", "scope"))

    if not region_id:
        if road_id or intersection_id:
            raise KnowledgeMetadataError("roadId/intersectionId 必须同时提供 regionId")
        grounding_scope = (
            GROUNDING_SCOPE_GLOBAL
            if explicit_scope == GROUNDING_SCOPE_GLOBAL
            else GROUNDING_SCOPE_LEGACY_UNSCOPED
        )
    else:
        if explicit_scope == GROUNDING_SCOPE_GLOBAL:
            raise KnowledgeMetadataError("GLOBAL 知识不能同时设置 regionId")
        grounding_scope = GROUNDING_SCOPE_REGIONAL

    effective_from = parse_effective_datetime(
        _first_present(meta, "effectiveFrom", "effective_from"), "effectiveFrom"
    )
    effective_to = parse_effective_datetime(
        _first_present(meta, "effectiveTo", "effective_to"), "effectiveTo"
    )
    if effective_from and effective_to and effective_to <= effective_from:
        raise KnowledgeMetadataError("effectiveTo 必须晚于 effectiveFrom")

    if validate_refs and region_id:
        repo = regional_repository or SQLiteRegionalRepository()
        region = repo.get_region(region_id)
        if region is None:
            raise KnowledgeMetadataError(f"regionId 不存在: {region_id}")
        if road_id:
            road = repo.get_road(road_id)
            if road is None:
                raise KnowledgeMetadataError(f"roadId 不存在: {road_id}")
            if road.get("regionId") != region_id:
                raise KnowledgeMetadataError(f"roadId 不属于 regionId: {road_id}")
        if intersection_id:
            intersection = repo.get_intersection(intersection_id)
            if intersection is None:
                raise KnowledgeMetadataError(f"intersectionId 不存在: {intersection_id}")
            if intersection.get("regionId") != region_id:
                raise KnowledgeMetadataError(f"intersectionId 不属于 regionId: {intersection_id}")

    return {
        "authority_level": _clean_text(_first_present(meta, "authorityLevel", "authority_level")),
        "source_uri": _clean_text(_first_present(meta, "sourceUri", "source_uri")),
        "event_type": normalize_event_type(_first_present(meta, "eventType", "event_type")),
        "road_name": _clean_text(_first_present(meta, "roadName", "road_name")),
        "risk_level": _clean_text(_first_present(meta, "riskLevel", "risk_level")),
        "jurisdiction": _clean_text(_first_present(meta, "jurisdiction")),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "region_id": region_id,
        "road_id": road_id,
        "intersection_id": intersection_id,
        "grounding_scope": grounding_scope,
    }


def regional_metadata_to_api(obj: Any) -> Dict[str, Any]:
    """Return canonical regional metadata using user-facing camelCase keys."""
    return {
        "regionId": getattr(obj, "region_id", None),
        "roadId": getattr(obj, "road_id", None),
        "intersectionId": getattr(obj, "intersection_id", None),
        "eventType": getattr(obj, "event_type", None),
        "groundingScope": getattr(obj, "grounding_scope", None) or GROUNDING_SCOPE_LEGACY_UNSCOPED,
        "authorityLevel": getattr(obj, "authority_level", None),
        "sourceUri": getattr(obj, "source_uri", None),
        "effectiveFrom": (
            getattr(obj, "effective_from", None).isoformat()
            if getattr(obj, "effective_from", None)
            else None
        ),
        "effectiveTo": (
            getattr(obj, "effective_to", None).isoformat()
            if getattr(obj, "effective_to", None)
            else None
        ),
        "legacyRoadName": getattr(obj, "road_name", None),
        "jurisdiction": getattr(obj, "jurisdiction", None),
    }
