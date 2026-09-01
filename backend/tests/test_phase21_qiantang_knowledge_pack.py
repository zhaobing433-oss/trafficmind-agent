"""Phase21 G2 Qiantang pilot Knowledge pack validation.

The formal pack is data-only. These tests ingest it through the existing
Knowledge/RAG V2 write path into temporary SQLite, Chroma, and FTS stores.
They must not import into backend/data/trafficmind.db, mutate the production
RAG database, or touch the active Qwen production collection.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qsl, urlparse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
import backend.tools.db_tools as db_tools
from backend.case_memory.repository import init_case_memory_tables
from backend.config import EVENT_BASE_SCORES
from backend.regional.importer import load_context_pack_from_directory
from backend.regional.repository import RegionalValidationError, SQLiteRegionalRepository
from backend.rag.v2.indexer import _make_document_id


REGION_ID = "QT_BY_XIASHA_PILOT_001"
KNOWLEDGE_PACK_DIR = Path(__file__).resolve().parents[1] / "data" / "pilot_knowledge" / "qt_by_xiasha_pilot_001"
REGION_PACK_DIR = Path(__file__).resolve().parents[1] / "data" / "pilot_regions" / "qt_by_xiasha_pilot_001"
PRODUCTION_DB = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
GENERIC_EVENT_TYPES = {"generic", "*", "all", "any"}
PRESCRIPTIVE_PATTERN = re.compile(r"(应当|应|必须|立即|优先|建议|禁止|不得|采取|处置|责令)")


def _load_json(name: str) -> Any:
    with (KNOWLEDGE_PACK_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


def _load_knowledge_pack() -> Dict[str, Any]:
    return {
        "package": _load_json("package.json"),
        "sources": _load_json("source_register.json")["sources"],
        "documents": _load_json("documents.json"),
    }


def _source_guidance_lines(content: str) -> List[str]:
    lines: List[str] = []
    in_source_guidance = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "SOURCE_GUIDANCE":
            in_source_guidance = True
            continue
        if stripped in {"APPLICABILITY", "LIMITATIONS"}:
            in_source_guidance = False
        if in_source_guidance and stripped.startswith("- "):
            lines.append(stripped)
    return lines


def _prescriptive_source_lines(document: Dict[str, Any]) -> List[str]:
    supported = set(document["metadata"].get("sourceSupportedPrescriptiveLines") or [])
    return [
        line
        for line in _source_guidance_lines(document["content"])
        if PRESCRIPTIVE_PATTERN.search(line) and line not in supported
    ]


def _canonical_event_types() -> set[str]:
    return set(EVENT_BASE_SCORES)


def _source_ids_from_register(pack: Dict[str, Any]) -> set[str]:
    return {source["sourceId"] for source in pack["sources"]}


def _source_by_id(pack: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {source["sourceId"]: source for source in pack["sources"]}


def _doc_spec_by_document_id(pack: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {document["documentId"]: document for document in pack["documents"]}


def _seed_event(
    event_id: str,
    *,
    road_name: str = "2号大街",
    event_type: str = "accident",
    event_type_cn: str = "事故",
    analyzed_at: str = "2026-06-30T08:00:00Z",
) -> None:
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": event_type,
            "eventTypeCn": event_type_cn,
            "roadName": road_name,
            "direction": "东向西",
            "avgSpeed": 9,
            "queueLength": 180,
            "duration": 3600,
            "weather": "rain",
            "timePeriod": "morning_peak",
            "isMainRoad": True,
            "nearbySchool": True,
            "nearbyHospital": False,
        },
        "riskScore": 92,
        "riskLevel": "重大风险",
        "status": "待派单",
        "report": "phase21 G2 isolated event fixture",
        "analyzedAt": analyzed_at,
    })


def _bind_event(
    repo: SQLiteRegionalRepository,
    event_id: str,
    *,
    road_id: str | None = "QT_BY_RD_NO2",
    intersection_id: str | None = None,
) -> None:
    repo.save_resolved_event_location_binding({
        "eventId": event_id,
        "status": "resolved",
        "resolutionMethod": "TEST_BINDING",
        "regionId": REGION_ID,
        "roadId": road_id,
        "intersectionId": intersection_id,
        "matchedAlias": "2号大街",
        "candidates": [],
    })


def _seed_region_b(repo: SQLiteRegionalRepository) -> None:
    repo.import_context_pack({
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_qiantang_knowledge_pack.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_B",
            "name": "测试区域B",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [{"roadId": "ROAD_B_OTHER", "regionId": "TEST_REGION_B", "name": "外环路"}],
        "intersections": [],
        "roadRelations": [],
        "pois": [],
    })


def _create_doc_from_pack(document: Dict[str, Any]) -> Dict[str, Any]:
    from backend.knowledge.service import create_document

    return create_document(
        name=document["title"],
        doc_type=document["docType"],
        content=document["content"],
        metadata=document["metadata"],
    )


def _create_test_doc(
    source_id: str,
    content: str,
    metadata: Dict[str, Any] | None = None,
    *,
    doc_type: str = "rule",
) -> Dict[str, Any]:
    from backend.knowledge.service import create_document

    return create_document(
        name=source_id,
        doc_type=doc_type,
        content=f"## {source_id}\n\n{content}",
        metadata={"sourceId": source_id, "authorityLevel": "official", **(metadata or {})},
    )


def _ingest_formal_pack() -> List[Dict[str, Any]]:
    return [_create_doc_from_pack(document) for document in _load_knowledge_pack()["documents"]]


def _document_by_source_id(source_id: str):
    from backend.rag.v2.document_repository import get_document

    return get_document(_make_document_id(source_id))


def _evidence_doc_ids(context: Dict[str, Any]) -> set[str]:
    return {item["documentId"] for item in context.get("evidence") or []}


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    event_db = str(tmp_path / "phase21_g2_events.db")
    rag_db = str(tmp_path / "phase21_g2_rag.db")
    fts_path = str(tmp_path / "phase21_g2_fts.db")
    chroma_path = str(tmp_path / "phase21_g2_chroma")
    assert event_db != PRODUCTION_DB

    monkeypatch.setattr(cfg, "DB_PATH", event_db)
    monkeypatch.setattr(db_tools, "DB_PATH", event_db)
    db_tools.init_db()
    init_case_memory_tables()

    import backend.rag.v2.config as v2cfg
    import backend.rag.v2.dense_index as dense_idx
    import backend.rag.v2.document_repository as doc_repo
    import backend.rag.v2.sparse_index as sparse_idx
    from backend.rag.v2.providers import FakeEmbeddingProvider, FakeRerankerProvider

    monkeypatch.setattr(v2cfg, "RAG_V2_DB_PATH", rag_db)
    monkeypatch.setattr(doc_repo, "RAG_V2_DB_PATH", rag_db)
    monkeypatch.setattr(v2cfg, "RAG_V2_FTS_PATH", fts_path)
    monkeypatch.setattr(sparse_idx, "RAG_V2_FTS_PATH", fts_path)
    dense_idx._VECTOR_DB_PATH = chroma_path
    monkeypatch.setattr(dense_idx, "_get_vector_db_path", lambda: chroma_path)

    fake_provider = FakeEmbeddingProvider(dimension=384)
    fake_reranker = FakeRerankerProvider()
    monkeypatch.setattr("backend.rag.v2.providers.get_embedding_provider", lambda: fake_provider)
    monkeypatch.setattr("backend.rag.v2.providers.get_reranker_provider", lambda: fake_reranker)
    monkeypatch.setattr("backend.knowledge.service.get_embedding_provider", lambda: fake_provider)

    import backend.knowledge.regional_context as knowledge_context

    monkeypatch.setattr(knowledge_context, "get_embedding_provider", lambda: fake_provider)

    sparse_idx.init_fts()
    doc_repo.init_db()

    repo = SQLiteRegionalRepository(db_path=event_db)
    repo.import_context_pack(load_context_pack_from_directory(REGION_PACK_DIR))
    _seed_region_b(repo)
    return {
        "tmpRoot": str(tmp_path),
        "eventDb": event_db,
        "ragDb": rag_db,
        "ftsPath": fts_path,
        "chromaPath": chroma_path,
        "repo": repo,
    }


def test_qiantang_knowledge_pack_contract_source_and_claims():
    pack = _load_knowledge_pack()
    source_ids = _source_ids_from_register(pack)
    documents = pack["documents"]
    canonical_types = _canonical_event_types()

    assert pack["package"]["regionId"] == REGION_ID
    assert pack["package"]["metadata"]["knowledgeArchitecture"] == "existing_rag_v2_documents"
    assert pack["package"]["metadata"]["scopeSemantics"]["GLOBAL"].startswith(
        "TrafficMind non-region-specific retrieval scope"
    )
    assert pack["package"]["metadata"]["safePilotEvaluationTimeRange"]["eventTimeFromInclusive"] == (
        "2024-08-01T00:00:00Z"
    )
    assert len(documents) >= 4
    assert len({d["metadata"]["eventType"] for d in documents if d["metadata"]["eventType"] not in GENERIC_EVENT_TYPES}) >= 3
    assert sum(1 for d in documents if d["metadata"].get("groundingScope") == "GLOBAL") >= 1
    assert sum(1 for d in documents if d["metadata"].get("groundingScope") == "REGIONAL") >= 1
    assert sum(1 for s in pack["sources"] if s["sourceTier"] == "A") >= 3

    for source in pack["sources"]:
        parsed = urlparse(source["sourceUrl"])
        assert parsed.scheme == "https"
        assert parsed.netloc
        tracking = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        assert not any(key.startswith("utm_") or key in {"session", "sid", "token"} for key in tracking)
        assert source["retrievedAt"] == "2026-09-01"
        assert source["authorityLevel"] == "official"
        assert source["issuingAuthority"]
        assert source["hostingOrganization"]
        assert source["versionOrAmendmentInfo"]
        assert source["currentStatusFromSource"]
        assert source["issuingAuthority"] != source["organization"]
        assert source["verificationNotes"]
        assert "licenseNote" in source

    for document in documents:
        assert document["documentId"] == document["metadata"]["sourceId"]
        assert document["docType"] in {"rule", "regulation", "other"}
        assert document["metadata"]["contentForm"] == "DERIVED_SOURCE_SUMMARY"
        assert document["metadata"]["sourceIds"]
        assert set(document["metadata"]["sourceIds"]).issubset(source_ids)
        assert document["metadata"]["sourceUri"] in {
            source["sourceUrl"] for source in pack["sources"] if source["sourceId"] in document["metadata"]["sourceIds"]
        }
        assert document["metadata"]["authorityLevel"] == "official"
        assert document["metadata"]["effectiveTo"] is None
        assert document["metadata"]["corpusStatusMeaning"].startswith("Document status active means enabled")
        assert document["metadata"]["sourceVersionProvenance"]
        assert document["metadata"]["temporalApplicabilityConfidence"]
        assert document["metadata"]["safePilotEvaluationTimeRange"] == "2024-08-01T00:00:00Z..open"
        if document["metadata"]["effectiveFrom"] is None:
            assert "not a claim" in document["metadata"]["nullEffectiveFromMeaning"]
        event_type = document["metadata"]["eventType"]
        assert event_type in canonical_types | GENERIC_EVENT_TYPES
        if document["metadata"]["groundingScope"] == "GLOBAL":
            assert not document["metadata"].get("regionId")
            assert document["metadata"]["globalScopeMeaning"].startswith("GLOBAL means non-region-specific")
            assert document["metadata"]["jurisdiction"] == "中华人民共和国"
        elif document["metadata"]["groundingScope"] == "REGIONAL":
            assert document["metadata"].get("regionId") == REGION_ID
            assert document["metadata"]["coverageSubset"]
            assert document["metadata"]["applicabilityLimitations"]
            assert document["metadata"]["ruleVsContext"] == "LOCAL_PUBLIC_POLICY_CONTEXT"
        else:
            pytest.fail(f"unsupported groundingScope: {document['metadata']['groundingScope']}")
        if document["metadata"].get("effectiveFrom"):
            assert document["metadata"]["effectiveDateBasis"]
            assert "explicitly lists" in document["metadata"]["effectiveDateBasis"]
        assert not _prescriptive_source_lines(document)
        assert "/Users/" not in json.dumps(document, ensure_ascii=False)
        assert "ChatGPT" not in json.dumps(document, ensure_ascii=False)
        executable_keys = {
            "actionType",
            "workflowStep",
            "workflowStepId",
            "toolCall",
            "toolName",
            "executionParameters",
            "dispatchAction",
        }
        assert executable_keys.isdisjoint(document["metadata"])

    readme = (KNOWLEDGE_PACK_DIR / "README.md").read_text(encoding="utf-8")
    for required in [
        "Source snapshot date: `2026-09-01`",
        "project-derived source-grounded summary",
        "not an official government knowledge base",
        "not a realtime policy feed",
        "`status=active` for an ingested document means \"enabled in the TrafficMind corpus\" only",
        "`GLOBAL` means non-region-specific retrieval inside the current China pilot product boundary",
        "`effectiveFrom=null` means the current Wave D filter has no lower-bound",
        "Safe G3 pilot evaluation range",
        "not a full Qiantang District knowledge corpus",
        "not a local dispatch SOP",
    ]:
        assert required in readme


def test_qiantang_knowledge_pack_validates_region_refs_and_rejects_bad_refs(isolated):
    _ingest_formal_pack()
    regional = _document_by_source_id("QT_KNOW_QIANTANG_BY_CONTEXT_001")
    assert regional is not None
    assert regional.region_id == REGION_ID
    assert regional.grounding_scope == "REGIONAL"

    with pytest.raises(Exception) as exc:
        _create_test_doc(
            "TEST_BAD_ROAD_REF",
            "bad regional ref",
            {"regionId": REGION_ID, "roadId": "QT_BY_RD_MISSING", "eventType": "congestion"},
        )
    assert "roadId 不存在" in str(exc.value)

    with pytest.raises(RegionalValidationError):
        isolated["repo"].import_context_pack({
            "packageVersion": 1,
            "region": {"regionId": "TEST_REGION_B", "name": "重复区域B", "city": "测试市", "timezone": "Asia/Shanghai"},
            "roads": [{"roadId": "QT_BY_RD_NO2", "regionId": "TEST_REGION_B", "name": "错误复用道路"}],
            "intersections": [],
            "roadRelations": [],
            "pois": [],
        })


def test_qiantang_knowledge_ingestion_isolated_idempotent_and_projects_metadata(isolated):
    for key in ("eventDb", "ragDb", "ftsPath", "chromaPath"):
        assert isolated[key].startswith(isolated["tmpRoot"])
        assert isolated[key] != PRODUCTION_DB

    first = _ingest_formal_pack()
    second = _ingest_formal_pack()
    assert [item["documentId"] for item in first] == [item["documentId"] for item in second]

    from backend.rag.v2.dense_index import get_collection, get_active_collection_name
    from backend.rag.v2.document_repository import get_chunks_by_document, get_document, list_active_documents

    active_docs = list_active_documents()
    assert len(active_docs) == len(_load_knowledge_pack()["documents"])
    assert all(doc.status == "active" for doc in active_docs)

    pack = _load_knowledge_pack()
    spec_by_source_id = {spec["metadata"]["sourceId"]: spec for spec in pack["documents"]}
    total_chunks = 0
    for spec in pack["documents"]:
        doc = get_document(_make_document_id(spec["metadata"]["sourceId"]))
        assert doc is not None
        expected_from = spec["metadata"]["effectiveFrom"]
        expected_to = spec["metadata"]["effectiveTo"]
        assert doc.source_uri == spec["metadata"]["sourceUri"]
        assert doc.event_type == spec["metadata"]["eventType"]
        assert doc.grounding_scope == spec["metadata"]["groundingScope"]
        assert doc.region_id == spec["metadata"].get("regionId")
        assert doc.jurisdiction == spec["metadata"]["jurisdiction"]
        assert (
            doc.effective_from.isoformat() if doc.effective_from else None
        ) == (expected_from.replace("Z", "+00:00") if expected_from else None)
        assert (
            doc.effective_to.isoformat() if doc.effective_to else None
        ) == (expected_to.replace("Z", "+00:00") if expected_to else None)
        chunks = get_chunks_by_document(doc.document_id, active_only=True)
        assert chunks
        total_chunks += len(chunks)
        for chunk in chunks:
            assert chunk.event_type == doc.event_type
            assert chunk.region_id == doc.region_id
            assert chunk.road_id == doc.road_id
            assert chunk.intersection_id == doc.intersection_id
            assert chunk.grounding_scope == doc.grounding_scope
            assert chunk.authority_level == doc.authority_level
            assert chunk.effective_from == doc.effective_from
            assert chunk.effective_to == doc.effective_to

    collection = get_collection(get_active_collection_name())
    assert collection is not None
    assert collection.count() == total_chunks
    vector_rows = collection.get(include=["metadatas"])
    assert vector_rows["metadatas"]
    by_doc = {metadata["document_id"]: metadata for metadata in vector_rows["metadatas"]}
    for doc in active_docs:
        spec = spec_by_source_id[doc.source_id]
        meta = by_doc[doc.document_id]
        assert meta["event_type"] == (doc.event_type or "")
        assert meta["region_id"] == (doc.region_id or "")
        assert meta["grounding_scope"] == doc.grounding_scope
        assert meta["authority_level"] == doc.authority_level
        assert meta["effective_from"] == (
            spec["metadata"]["effectiveFrom"].replace("Z", "+00:00")
            if spec["metadata"]["effectiveFrom"]
            else ""
        )
        assert meta["effective_to"] == (
            spec["metadata"]["effectiveTo"].replace("Z", "+00:00")
            if spec["metadata"]["effectiveTo"]
            else ""
        )

    with sqlite3.connect(isolated["ftsPath"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0] == total_chunks


def test_event_context_eligibility_excludes_wrong_region_event_type_time_status_and_legacy(
    isolated,
    monkeypatch,
):
    _ingest_formal_pack()
    _seed_event("E_G2_ACCIDENT", event_type="accident", event_type_cn="事故", analyzed_at="2026-06-30T08:00:00Z")
    _bind_event(isolated["repo"], "E_G2_ACCIDENT")

    include_boundary = _create_test_doc(
        "TEST_EFFECTIVE_FROM_EQUAL_T0",
        "事故 边界 包含",
        {
            "regionId": REGION_ID,
            "eventType": "accident",
            "effectiveFrom": "2026-06-30T08:00:00Z",
            "sourceUri": "manual://include-boundary",
        },
    )
    excluded_to_boundary = _create_test_doc(
        "TEST_EFFECTIVE_TO_EQUAL_T0",
        "事故 到点 过期",
        {
            "regionId": REGION_ID,
            "eventType": "accident",
            "effectiveTo": "2026-06-30T08:00:00Z",
            "sourceUri": "manual://exclude-boundary",
        },
    )
    excluded_future = _create_test_doc(
        "TEST_FUTURE_ACCIDENT",
        "事故 未来 文档",
        {
            "regionId": REGION_ID,
            "eventType": "accident",
            "effectiveFrom": "2030-01-01T00:00:00Z",
            "sourceUri": "manual://future",
        },
    )
    excluded_expired = _create_test_doc(
        "TEST_EXPIRED_ACCIDENT",
        "事故 过期 文档",
        {
            "regionId": REGION_ID,
            "eventType": "accident",
            "effectiveTo": "2026-01-01T00:00:00Z",
            "sourceUri": "manual://expired",
        },
    )
    excluded_wrong_region = _create_test_doc(
        "TEST_WRONG_REGION_HIGH_AUTHORITY",
        "事故 其他区域 高权威",
        {
            "regionId": "TEST_REGION_B",
            "eventType": "accident",
            "authorityLevel": "official",
            "sourceUri": "manual://wrong-region",
        },
    )
    excluded_type = _document_by_source_id("QT_KNOW_ILLEGAL_PARKING_REG_001")
    excluded_legacy = _create_test_doc("TEST_LEGACY_UNSCOPED", "旧无范围不能当成全局。")
    inactive = _create_test_doc(
        "TEST_INACTIVE_ACCIDENT",
        "事故 停用 文档",
        {"regionId": REGION_ID, "eventType": "accident", "sourceUri": "manual://inactive"},
    )
    conn = sqlite3.connect(isolated["ragDb"])
    try:
        conn.execute("UPDATE rag_documents SET status='draft' WHERE document_id=?", (inactive["documentId"],))
        conn.commit()
    finally:
        conn.close()

    captured: Dict[str, List[str]] = {}

    def fake_retrieve(self, query, rewritten_query="", analysis=None, top_k=30, **kwargs):
        allowed = sorted(kwargs.get("allowed_document_ids") or [])
        captured["allowed"] = allowed
        from backend.rag.v2.document_repository import get_chunks_by_document, get_document

        rows = []
        for idx, doc_id in enumerate(allowed):
            doc = get_document(doc_id)
            chunk = get_chunks_by_document(doc_id, active_only=True)[0]
            rows.append({
                "chunk_id": chunk.chunk_id,
                "document_id": doc_id,
                "parent_chunk_id": chunk.parent_chunk_id,
                "content": chunk.contextual_content,
                "contextual_content": chunk.contextual_content,
                "section_path": chunk.section_path,
                "doc_type": chunk.doc_type,
                "title": doc.title,
                "authority_level": doc.authority_level,
                "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
                "effective_to": doc.effective_to.isoformat() if doc.effective_to else None,
                "source_uri": doc.source_uri,
                "event_type": doc.event_type,
                "region_id": doc.region_id,
                "road_id": doc.road_id,
                "intersection_id": doc.intersection_id,
                "grounding_scope": doc.grounding_scope,
                "score": 1.0 - (idx * 0.01),
                "sparse_rank": idx + 1,
                "channel": "sparse",
                "retrieval_channels": ["sparse"],
            })
        return rows

    monkeypatch.setattr("backend.rag.v2.hybrid_retriever.HybridRetriever.retrieve", fake_retrieve)

    from backend.knowledge.regional_context import EventKnowledgeContextService

    context = EventKnowledgeContextService(isolated["repo"]).get_context_for_event(
        "E_G2_ACCIDENT",
        query="事故 现场 保护 报警",
        limit=20,
    )
    allowed = set(captured["allowed"])
    assert _make_document_id("QT_KNOW_ACCIDENT_LAW_001") in allowed
    assert _make_document_id("QT_KNOW_QIANTANG_BY_CONTEXT_001") in allowed
    assert include_boundary["documentId"] in allowed
    assert excluded_to_boundary["documentId"] not in allowed
    assert excluded_future["documentId"] not in allowed
    assert excluded_expired["documentId"] not in allowed
    assert excluded_wrong_region["documentId"] not in allowed
    assert excluded_type.document_id not in allowed
    assert excluded_legacy["documentId"] not in allowed
    assert inactive["documentId"] not in allowed
    assert context["provenance"]["applicabilityFilter"] == "structured_pre_retrieval"


def test_global_vs_regional_and_unresolved_location_semantics(isolated):
    _ingest_formal_pack()
    _seed_event("E_G2_UNRESOLVED", road_name="未知路段", event_type="accident", event_type_cn="事故")
    _seed_event("E_G2_REGIONAL", road_name="2号大街", event_type="accident", event_type_cn="事故")
    _bind_event(isolated["repo"], "E_G2_REGIONAL")
    _seed_event("E_G2_REGION_B", road_name="外环路", event_type="accident", event_type_cn="事故")
    isolated["repo"].save_resolved_event_location_binding({
        "eventId": "E_G2_REGION_B",
        "status": "resolved",
        "resolutionMethod": "TEST_BINDING",
        "regionId": "TEST_REGION_B",
        "roadId": "ROAD_B_OTHER",
        "intersectionId": None,
        "matchedAlias": "外环路",
        "candidates": [],
    })

    from backend.knowledge.regional_context import EventKnowledgeContextService

    service = EventKnowledgeContextService(isolated["repo"])
    context = service.get_context_for_event(
        "E_G2_UNRESOLVED",
        query="事故 现场 保护 报警",
        limit=10,
    )
    doc_ids = _evidence_doc_ids(context)
    assert context["reason"] == "LOCATION_UNRESOLVED_GLOBAL_ONLY"
    assert _make_document_id("QT_KNOW_ACCIDENT_LAW_001") in doc_ids
    assert _make_document_id("QT_KNOW_QIANTANG_BY_CONTEXT_001") not in doc_ids
    assert all(item["groundingScope"] == "GLOBAL" for item in context["evidence"])

    regional_context = service.get_context_for_event(
        "E_G2_REGIONAL",
        query="白杨单元 钱塘 规划 背景",
        limit=10,
    )
    assert _make_document_id("QT_KNOW_QIANTANG_BY_CONTEXT_001") in _evidence_doc_ids(regional_context)

    region_b_context = service.get_context_for_event(
        "E_G2_REGION_B",
        query="白杨单元 钱塘 规划 背景",
        limit=10,
    )
    assert _make_document_id("QT_KNOW_QIANTANG_BY_CONTEXT_001") not in _evidence_doc_ids(region_b_context)


def test_retrieval_quality_smoke_for_formal_pilot_event_types(isolated):
    _ingest_formal_pack()
    event_cases = [
        ("E_ACCIDENT", "accident", "事故", "路口追尾后有人受伤需要报警和保护现场", "QT_KNOW_ACCIDENT_LAW_001"),
        ("E_CONGESTION", "congestion", "拥堵", "早高峰路口车流排队已经压到停止线外", "QT_KNOW_CONGESTION_REG_001"),
        ("E_PARKING", "illegal_parking", "违停", "急救站附近临停车辆影响其它车辆通行", "QT_KNOW_ILLEGAL_PARKING_REG_001"),
        ("E_STOPPED", "vehicle_stopped", "车辆滞留", "故障车停在车道里需要警示和移到安全位置", "QT_KNOW_VEHICLE_STOPPED_REG_001"),
        ("E_PEDESTRIAN", "pedestrian_intrusion", "行人闯入", "学校医院门前行人过街需要车辆避让", "QT_KNOW_PEDESTRIAN_LAW_001"),
        ("E_SIGNAL", "signal_fault", "信号灯异常", "路口信号灯装设位置和安装状态异常依据", "QT_KNOW_SIGNAL_GB14886_001"),
    ]
    pack = _load_knowledge_pack()
    spec_by_id = _doc_spec_by_document_id(pack)
    source_urls = {source["sourceUrl"] for source in pack["sources"]}

    from backend.knowledge.regional_context import EventKnowledgeContextService
    from backend.rag.v2.document_repository import get_chunks_by_document, get_document

    service = EventKnowledgeContextService(isolated["repo"])
    for event_id, event_type, event_type_cn, query, expected_source_id in event_cases:
        expected_spec = spec_by_id[expected_source_id]
        assert expected_spec["title"] not in query
        _seed_event(event_id, event_type=event_type, event_type_cn=event_type_cn)
        _bind_event(isolated["repo"], event_id)
        context = service.get_context_for_event(event_id, query=query, limit=10)
        assert context["status"] == "ready"
        assert context["evidenceState"] == "available"
        assert _make_document_id(expected_source_id) in _evidence_doc_ids(context)
        for item in context["evidence"]:
            doc = get_document(item["documentId"])
            assert doc is not None
            chunk_texts = {chunk.contextual_content for chunk in get_chunks_by_document(doc.document_id, active_only=True)}
            assert item["chunkId"]
            assert item["sourceUri"] == doc.source_uri
            assert item["sourceUri"] in source_urls
            assert item["content"] in chunk_texts
            assert item["regionalMetadata"]["scopeMatch"] in {"global", "region"}
            assert item["regionalMetadata"]["sourceUri"] == item["sourceUri"]


def test_g1_plus_g2_grounded_context_smoke_with_empty_history_and_cases(isolated):
    _ingest_formal_pack()
    _seed_event("E_G2_GROUNDED", event_type="congestion", event_type_cn="拥堵")
    _bind_event(isolated["repo"], "E_G2_GROUNDED")

    from backend.grounding.assembler import GroundedEventContextAssembler

    context = GroundedEventContextAssembler(regional_repository=isolated["repo"]).assemble(
        "E_G2_GROUNDED",
        query="交叉路口 交通阻塞 等候",
        knowledge_top_k=5,
        case_top_k=5,
    ).to_dict()

    assert context["regionalContext"]["status"] == "READY"
    assert context["regionalContext"]["location"]["regionId"] == REGION_ID
    assert context["knowledgeContext"]["status"] == "READY"
    assert context["knowledgeContext"]["evidence"]
    assert any(ref["type"] == "knowledge_evidence" for ref in context["groundingRefs"])
    assert context["historicalContext"]["status"] in {"EMPTY", "UNAVAILABLE", "READY"}
    assert context["caseMemoryContext"]["status"] in {"EMPTY", "UNAVAILABLE"}
    assert context["currentEvent"]["eventId"] == "E_G2_GROUNDED"


def test_near_duplicate_and_pack_runtime_safety():
    pack = _load_knowledge_pack()
    contents = [
        re.sub(r"\s+", "", document["content"])
        for document in pack["documents"]
    ]
    near_duplicates = 0
    for index, content in enumerate(contents):
        for other in contents[index + 1:]:
            if SequenceMatcher(None, content, other).ratio() >= 0.92:
                near_duplicates += 1
    assert near_duplicates == 0
    assert not any(
        document["metadata"]["ruleVsContext"] == "LOCAL_PUBLIC_POLICY_CONTEXT"
        and document["metadata"]["eventType"] != "generic"
        for document in pack["documents"]
    )
