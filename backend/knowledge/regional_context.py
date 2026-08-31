"""Event-bound Knowledge context for Phase21 regional applicability.

This service is read-only. It hydrates the authoritative traffic event, reads
the active canonical location binding, filters applicable knowledge before
ranking, and returns auditable evidence metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.knowledge.regional_metadata import (
    GROUNDING_SCOPE_GLOBAL,
    GROUNDING_SCOPE_LEGACY_UNSCOPED,
    event_type_applicable,
    regional_metadata_to_api,
)
from backend.rag.v2.document_repository import get_chunks_by_document, list_active_documents
from backend.rag.v2.hybrid_retriever import HybridRetriever
from backend.rag.v2.models import EvidenceItem, QueryAnalysis, RagDocument
from backend.rag.v2.providers import get_embedding_provider
from backend.rag.v2.reranker import Reranker
from backend.regional.repository import SQLiteRegionalRepository
from backend.tools.event_identity import (
    EventIdentityError,
    compact_event_context,
    extract_event_id,
    hydrate_authoritative_event,
)


class KnowledgeContextError(ValueError):
    """Knowledge context error with HTTP status hint."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_event_time(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _effective_at(doc: RagDocument, as_of: datetime) -> bool:
    effective_from = _ensure_utc(doc.effective_from)
    effective_to = _ensure_utc(doc.effective_to)
    if effective_from and effective_from > as_of:
        return False
    if effective_to and not (as_of < effective_to):
        return False
    return True


def _location_match(
    doc: RagDocument,
    binding: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    scope = (doc.grounding_scope or GROUNDING_SCOPE_LEGACY_UNSCOPED).upper()
    if scope == GROUNDING_SCOPE_GLOBAL:
        return True, "global"
    if scope == GROUNDING_SCOPE_LEGACY_UNSCOPED and not doc.region_id:
        return False, "legacy_unscoped"
    if not binding or not binding.get("regionId"):
        return False, "unresolved_location"
    if doc.region_id != binding.get("regionId"):
        return False, "region_mismatch"

    event_intersection_id = binding.get("intersectionId")
    event_road_id = binding.get("roadId")
    if event_intersection_id:
        if doc.intersection_id and doc.intersection_id == event_intersection_id:
            return True, "intersection"
        if not doc.intersection_id and not doc.road_id:
            return True, "region"
        return False, "location_mismatch"

    if event_road_id:
        if doc.road_id and not doc.intersection_id and doc.road_id == event_road_id:
            return True, "road"
        if not doc.road_id and not doc.intersection_id:
            return True, "region"
        return False, "location_mismatch"

    return False, "unresolved_location"


def _evidence_to_dto(
    evidence: EvidenceItem,
    doc: RagDocument,
    *,
    rank: int,
    scope_match: str,
) -> Dict[str, Any]:
    regional = regional_metadata_to_api(doc)
    regional["scopeMatch"] = scope_match
    return {
        "evidenceId": evidence.evidence_id or f"E{rank}",
        "documentId": doc.document_id,
        "chunkId": evidence.chunk_id,
        "parentChunkId": evidence.parent_chunk_id,
        "title": doc.title,
        "docType": doc.doc_type,
        "sectionPath": evidence.section_path,
        "content": evidence.content,
        "contextualContent": evidence.contextual_content,
        "authorityLevel": doc.authority_level,
        "sourceUri": doc.source_uri,
        "effectiveFrom": doc.effective_from.isoformat() if doc.effective_from else None,
        "effectiveTo": doc.effective_to.isoformat() if doc.effective_to else None,
        "eventType": doc.event_type,
        "roadName": doc.road_name,
        "regionId": doc.region_id,
        "roadId": doc.road_id,
        "intersectionId": doc.intersection_id,
        "groundingScope": doc.grounding_scope,
        "score": evidence.rerank_score or evidence.rrf_score or evidence.dense_score,
        "retrievalChannels": evidence.retrieval_channels,
        "regionalMetadata": regional,
    }


def _candidate_doc_id(candidate: Dict[str, Any]) -> str:
    if candidate.get("document_id"):
        return str(candidate["document_id"])
    metadata = candidate.get("metadata")
    if isinstance(metadata, dict) and metadata.get("document_id"):
        return str(metadata["document_id"])
    return ""


class EventKnowledgeContextService:
    """Build event-bound knowledge context from existing RAG V2 documents."""

    def __init__(self, regional_repository: Optional[SQLiteRegionalRepository] = None):
        self.regional_repository = regional_repository or SQLiteRegionalRepository()

    def get_context_for_event(
        self,
        event_id: str,
        *,
        query: str = "",
        limit: int = 5,
    ) -> Dict[str, Any]:
        canonical_event_id = str(event_id or "").strip()
        try:
            snapshot = hydrate_authoritative_event(canonical_event_id)
        except EventIdentityError as err:
            raise KnowledgeContextError(err.code, err.message, 404 if err.code == "event_not_found" else 400)

        event = compact_event_context(snapshot)
        as_of = _parse_event_time(snapshot.get("createdAt"))
        if as_of is None:
            return self._unavailable(canonical_event_id, "INVALID_EVENT_CREATED_AT", event, None)

        binding = self.regional_repository.get_active_event_location_binding(canonical_event_id)
        location_resolved = bool(binding and binding.get("regionId"))
        target_event_type = str(event.get("eventType") or "").strip()
        retrieval_query = (query or "").strip() or self._default_query(event)

        eligible_docs: Dict[str, RagDocument] = {}
        doc_scope_matches: Dict[str, str] = {}
        eligible_chunk_count = 0
        excluded = {
            "legacyUnscoped": 0,
            "location": 0,
            "eventType": 0,
            "effectiveTime": 0,
        }
        for doc in list_active_documents():
            scope_ok, scope_match = _location_match(doc, binding)
            if not scope_ok:
                if scope_match == "legacy_unscoped":
                    excluded["legacyUnscoped"] += 1
                else:
                    excluded["location"] += 1
                continue
            if not event_type_applicable(doc.event_type, target_event_type):
                excluded["eventType"] += 1
                continue
            if not _effective_at(doc, as_of):
                excluded["effectiveTime"] += 1
                continue
            chunks = get_chunks_by_document(doc.document_id, active_only=True)
            if not chunks:
                continue
            eligible_docs[doc.document_id] = doc
            doc_scope_matches[doc.document_id] = scope_match
            eligible_chunk_count += len(chunks)

        evidence = self._retrieve_eligible_evidence(
            retrieval_query,
            eligible_docs,
            doc_scope_matches,
            as_of=as_of,
            limit=max(1, min(limit, 20)),
        )

        return {
            "status": "ready",
            "reason": None if location_resolved else "LOCATION_UNRESOLVED_GLOBAL_ONLY",
            "eventId": extract_event_id(snapshot),
            "query": retrieval_query,
            "scope": {
                "eventId": extract_event_id(snapshot),
                "regionId": binding.get("regionId") if binding else None,
                "roadId": binding.get("roadId") if binding else None,
                "intersectionId": binding.get("intersectionId") if binding else None,
                "eventType": target_event_type or None,
                "asOf": as_of.isoformat(),
                "locationResolved": location_resolved,
                "bindingId": binding.get("bindingId") if binding else None,
                "bindingSource": "event_location_bindings" if binding else None,
            },
            "totalEligibleChunks": eligible_chunk_count,
            "evidenceCount": len(evidence),
            "evidence": evidence,
            "evidenceState": "available" if evidence else "empty",
            "regionalGroundingStatus": self._grounding_status(location_resolved, evidence),
            "excluded": excluded,
            "provenance": {
                "sourceType": "event_records",
                "bindingSource": "event_location_bindings",
                "applicabilityFilter": "structured_pre_retrieval",
                "globalKnowledgePolicy": "explicit_global_only",
                "legacyUnscopedPolicy": "excluded_from_event_bound_context",
                "connectedRoadExpansion": False,
                "retrievalPipeline": "rag_v2_hybrid_rrf_reranker",
                "capturedAt": _utc_now_iso(),
            },
        }

    def _default_query(self, event: Dict[str, Any]) -> str:
        parts = [
            str(event.get("roadName") or "").strip(),
            str(event.get("eventTypeCn") or event.get("eventType") or "").strip(),
            "处置原则",
            "证据依据",
        ]
        return " ".join(part for part in parts if part)

    def _unavailable(
        self,
        event_id: str,
        reason: str,
        event: Dict[str, Any],
        binding: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "status": "unavailable",
            "reason": reason,
            "eventId": event_id,
            "query": self._default_query(event),
            "scope": {
                "eventId": event_id,
                "regionId": binding.get("regionId") if binding else None,
                "roadId": binding.get("roadId") if binding else None,
                "intersectionId": binding.get("intersectionId") if binding else None,
                "eventType": event.get("eventType") or None,
                "asOf": None,
                "locationResolved": bool(binding),
                "bindingId": binding.get("bindingId") if binding else None,
                "bindingSource": "event_location_bindings" if binding else None,
            },
            "totalEligibleChunks": 0,
            "evidenceCount": 0,
            "evidence": [],
            "evidenceState": "unavailable",
            "regionalGroundingStatus": "UNAVAILABLE",
            "excluded": {},
            "provenance": {
                "sourceType": "event_records",
                "bindingSource": "event_location_bindings",
                "applicabilityFilter": "structured_pre_retrieval",
                "connectedRoadExpansion": False,
                "capturedAt": _utc_now_iso(),
            },
        }

    def _retrieve_eligible_evidence(
        self,
        query: str,
        eligible_docs: Dict[str, RagDocument],
        doc_scope_matches: Dict[str, str],
        *,
        as_of: datetime,
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not eligible_docs:
            return []
        analysis = QueryAnalysis(
            needs_retrieval=True,
            filters={},
            reason="event_bound_structured_applicability",
        )
        candidates = HybridRetriever(get_embedding_provider()).retrieve(
            query,
            analysis=analysis,
            top_k=max(limit * 4, 12),
            allowed_document_ids=sorted(eligible_docs.keys()),
        )
        candidates = [c for c in candidates if _candidate_doc_id(c) in eligible_docs]
        reranker = Reranker(policy_as_of=as_of)
        accepted, _, _ = reranker.rerank(query, candidates)
        evidence_items = reranker.build_evidence_items(accepted[:limit], query)
        result = []
        for idx, item in enumerate(evidence_items, start=1):
            doc = eligible_docs.get(item.document_id)
            if not doc:
                continue
            result.append(
                _evidence_to_dto(
                    item,
                    doc,
                    rank=idx,
                    scope_match=doc_scope_matches.get(item.document_id, ""),
                )
            )
        return result

    def _grounding_status(self, location_resolved: bool, evidence: List[Dict[str, Any]]) -> str:
        if not evidence:
            return "NO_APPLICABLE_EVIDENCE" if location_resolved else "GLOBAL_ONLY_EMPTY"
        matches = {
            item.get("regionalMetadata", {}).get("scopeMatch")
            for item in evidence
            if isinstance(item.get("regionalMetadata"), dict)
        }
        if matches and matches <= {"global"}:
            return "GLOBAL_ONLY"
        return "REGIONAL_GROUNDED" if location_resolved else "GLOBAL_ONLY"
