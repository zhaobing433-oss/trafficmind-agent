"""Phase21 Wave D Knowledge regional metadata and event-bound context tests.

All tests use isolated temporary SQLite/RAG/Chroma state. They must not touch
backend/data/trafficmind.db, the active Qwen index, or the production corpus.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
import backend.tools.db_tools as db_tools
from backend.regional.repository import SQLiteRegionalRepository


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    production_db = str(Path(__file__).resolve().parents[1] / "data" / "trafficmind.db")
    event_db = str(tmp_path / "phase21_wave_d_events.db")
    rag_db = str(tmp_path / "phase21_wave_d_rag.db")
    chroma_path = str(tmp_path / "phase21_wave_d_chroma")
    fts_path = str(tmp_path / "phase21_wave_d_fts.db")
    assert event_db != production_db

    monkeypatch.setattr(cfg, "DB_PATH", event_db)
    monkeypatch.setattr(db_tools, "DB_PATH", event_db)
    db_tools.init_db()

    import backend.rag.v2.config as v2cfg
    import backend.rag.v2.document_repository as doc_repo
    import backend.rag.v2.dense_index as dense_idx
    from backend.rag.v2.providers import FakeEmbeddingProvider, FakeRerankerProvider

    monkeypatch.setattr(v2cfg, "RAG_V2_DB_PATH", rag_db)
    monkeypatch.setattr(doc_repo, "RAG_V2_DB_PATH", rag_db)
    monkeypatch.setattr(v2cfg, "RAG_V2_FTS_PATH", fts_path)
    dense_idx._VECTOR_DB_PATH = chroma_path
    monkeypatch.setattr(dense_idx, "_get_vector_db_path", lambda: chroma_path)

    fake_provider = FakeEmbeddingProvider(dimension=384)
    fake_reranker = FakeRerankerProvider()
    monkeypatch.setattr("backend.rag.v2.providers.get_embedding_provider", lambda: fake_provider)
    monkeypatch.setattr("backend.rag.v2.providers.get_reranker_provider", lambda: fake_reranker)
    monkeypatch.setattr("backend.knowledge.service.get_embedding_provider", lambda: fake_provider)

    import backend.rag.v2.sparse_index as sparse_idx

    monkeypatch.setattr(sparse_idx, "RAG_V2_FTS_PATH", fts_path)
    sparse_idx.init_fts()
    doc_repo.init_db()

    repo = SQLiteRegionalRepository(db_path=event_db)
    repo.import_context_pack(_context_pack())
    return {
        "eventDb": event_db,
        "ragDb": rag_db,
        "productionDb": production_db,
        "repo": repo,
        "fakeProvider": fake_provider,
    }


@pytest.fixture()
def repo(isolated):
    return isolated["repo"]


@pytest.fixture()
def api_client(isolated):
    from backend.knowledge.api import router as knowledge_router

    app = FastAPI()
    app.include_router(knowledge_router)
    return TestClient(app)


def _context_pack() -> dict:
    return {
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_knowledge_region_metadata.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_A",
            "name": "测试区域A",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [
            {"roadId": "ROAD_A_PEOPLE", "regionId": "TEST_REGION_A", "name": "人民路"},
            {"roadId": "ROAD_A_LIBERATION", "regionId": "TEST_REGION_A", "name": "解放路"},
        ],
        "intersections": [
            {
                "intersectionId": "INT_A_PEOPLE_LIBERATION",
                "regionId": "TEST_REGION_A",
                "name": "人民路-解放路路口",
            }
        ],
        "roadRelations": [
            {
                "relationId": "REL_A_PEOPLE_CONNECT",
                "regionId": "TEST_REGION_A",
                "fromEntityType": "road",
                "fromEntityId": "ROAD_A_PEOPLE",
                "toEntityType": "intersection",
                "toEntityId": "INT_A_PEOPLE_LIBERATION",
                "relationType": "connects",
            }
        ],
        "pois": [],
    }


def _seed_region_b(repo: SQLiteRegionalRepository) -> None:
    repo.import_context_pack({
        "packageVersion": 1,
        "sourceType": "synthetic_fixture",
        "sourceReference": "backend/tests/test_phase21_knowledge_region_metadata.py",
        "verificationStatus": "synthetic",
        "region": {
            "regionId": "TEST_REGION_B",
            "name": "测试区域B",
            "city": "测试市",
            "timezone": "Asia/Shanghai",
        },
        "roads": [{"roadId": "ROAD_B_OTHER", "regionId": "TEST_REGION_B", "name": "外环路"}],
        "intersections": [
            {
                "intersectionId": "INT_B_OTHER",
                "regionId": "TEST_REGION_B",
                "name": "外环路-支路路口",
            }
        ],
        "roadRelations": [],
        "pois": [],
    })


def _seed_event(event_id: str, road_name: str = "人民路", event_type: str = "congestion") -> None:
    event_type_cn = "拥堵" if event_type == "congestion" else "事故"
    assert db_tools.save_event_analysis({
        "eventId": event_id,
        "standardEvent": {
            "eventId": event_id,
            "eventType": event_type,
            "eventTypeCn": event_type_cn,
            "roadName": road_name,
            "direction": "东向西",
            "avgSpeed": 12,
            "queueLength": 80,
            "duration": 600,
        },
        "riskScore": 80,
        "riskLevel": "高风险",
        "status": "待派单",
        "report": "synthetic fixture",
        "analyzedAt": "2026-06-30T08:00:00+00:00",
    })


def _bind_event(
    repo: SQLiteRegionalRepository,
    event_id: str,
    *,
    road_id: str | None = "ROAD_A_PEOPLE",
    intersection_id: str | None = None,
) -> None:
    repo.save_resolved_event_location_binding({
        "eventId": event_id,
        "status": "resolved",
        "resolutionMethod": "TEST_BINDING",
        "regionId": "TEST_REGION_A",
        "roadId": road_id,
        "intersectionId": intersection_id,
        "matchedAlias": "人民路",
        "candidates": [],
    })


def _create_doc(name: str, content: str, metadata: dict | None = None) -> dict:
    from backend.knowledge.service import create_document

    return create_document(
        name=name,
        doc_type="rule",
        content=f"## {name}\n\n{content}",
        metadata={
            "sourceId": f"test:{name}",
            **(metadata or {}),
        },
    )


def _evidence_doc_ids(context: dict) -> set[str]:
    return {item["documentId"] for item in context["evidence"]}


def test_document_metadata_validates_refs_and_projects_to_chunks(isolated):
    summary = _create_doc(
        "人民路拥堵处置规则",
        "人民路拥堵时先分流并调整信号配时。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "effectiveFrom": "2025-01-01T00:00:00Z",
            "authorityLevel": "official",
            "sourceUri": "manual://people-road-congestion",
            "roadName": "人民路",
            "jurisdiction": "测试辖区",
        },
    )

    from backend.rag.v2.document_repository import get_chunks_by_document, get_document

    doc = get_document(summary["documentId"])
    assert doc.region_id == "TEST_REGION_A"
    assert doc.road_id == "ROAD_A_PEOPLE"
    assert doc.intersection_id is None
    assert doc.event_type == "congestion"
    assert doc.grounding_scope == "REGIONAL"
    assert doc.road_name == "人民路"

    chunks = get_chunks_by_document(doc.document_id, active_only=True)
    assert chunks
    assert all(chunk.region_id == "TEST_REGION_A" for chunk in chunks)
    assert all(chunk.road_id == "ROAD_A_PEOPLE" for chunk in chunks)
    assert all(chunk.event_type == "congestion" for chunk in chunks)
    assert all(chunk.grounding_scope == "REGIONAL" for chunk in chunks)

    assert summary["regionId"] == "TEST_REGION_A"
    assert summary["regionalMetadata"]["sourceUri"] == "manual://people-road-congestion"


def test_metadata_rejects_road_without_region_and_cross_region_refs(isolated, repo):
    from backend.knowledge.service import KnowledgeError

    with pytest.raises(KnowledgeError) as exc:
        _create_doc(
            "缺少区域的道路规则",
            "道路级规则必须提供区域。",
            {"roadId": "ROAD_A_PEOPLE"},
        )
    assert "regionId" in str(exc.value)

    _seed_region_b(repo)
    with pytest.raises(KnowledgeError) as exc2:
        _create_doc(
            "跨区域道路规则",
            "道路不能挂到错误区域。",
            {"regionId": "TEST_REGION_A", "roadId": "ROAD_B_OTHER"},
        )
    assert "roadId 不属于 regionId" in str(exc2.value)

    with pytest.raises(KnowledgeError) as exc3:
        _create_doc(
            "跨区域路口规则",
            "路口不能挂到错误区域。",
            {"regionId": "TEST_REGION_A", "intersectionId": "INT_B_OTHER"},
        )
    assert "intersectionId 不属于 regionId" in str(exc3.value)


def test_explicit_global_is_distinct_from_legacy_unscoped(isolated):
    legacy = _create_doc("旧无范围规则", "旧数据没有显式全局范围。")
    global_doc = _create_doc(
        "显式全局规则",
        "所有区域都可使用的通用处置原则。",
        {"groundingScope": "GLOBAL", "eventType": "generic"},
    )

    from backend.rag.v2.document_repository import get_document

    legacy_doc = get_document(legacy["documentId"])
    explicit_global = get_document(global_doc["documentId"])
    assert legacy_doc.grounding_scope == "LEGACY_UNSCOPED"
    assert explicit_global.grounding_scope == "GLOBAL"
    assert explicit_global.region_id is None


def test_event_context_filters_by_road_type_and_effective_time(isolated, repo):
    _seed_event("E_KNOW_ROAD")
    _bind_event(repo, "E_KNOW_ROAD", road_id="ROAD_A_PEOPLE")

    include_road = _create_doc(
        "人民路道路级拥堵规则",
        "人民路拥堵时优先实施道路分流。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "effectiveFrom": "2020-01-01T00:00:00Z",
            "sourceUri": "manual://road",
        },
    )
    include_region = _create_doc(
        "测试区域通用拥堵规则",
        "测试区域拥堵时先保障主干路通行。",
        {"regionId": "TEST_REGION_A", "eventType": "congestion"},
    )
    include_global = _create_doc(
        "全局通用交通规则",
        "通用交通事件均需记录证据。",
        {"groundingScope": "GLOBAL", "eventType": "generic"},
    )
    include_start_boundary = _create_doc(
        "事件时刻生效规则",
        "effectiveFrom 等于事件时间时应当适用。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "effectiveFrom": "2026-06-30T08:00:00+00:00",
        },
    )
    include_historical_valid = _create_doc(
        "事件后才过期规则",
        "规则在事件发生时仍有效，不能按当前时间误判过期。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "effectiveFrom": "2020-01-01T00:00:00Z",
            "effectiveTo": "2026-07-01T00:00:00Z",
        },
    )
    excluded_other_road = _create_doc(
        "解放路道路级规则",
        "解放路拥堵规则不适用于人民路。",
        {"regionId": "TEST_REGION_A", "roadId": "ROAD_A_LIBERATION", "eventType": "congestion"},
    )
    excluded_type = _create_doc(
        "人民路事故规则",
        "事故处置不应被拥堵事件选中。",
        {"regionId": "TEST_REGION_A", "roadId": "ROAD_A_PEOPLE", "eventType": "accident"},
    )
    excluded_future = _create_doc(
        "未来生效规则",
        "未来规则不能泄漏给历史事件。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "effectiveFrom": "2030-01-01T00:00:00Z",
        },
    )
    excluded_expired = _create_doc(
        "到点过期规则",
        "effectiveTo 使用右开边界。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "effectiveTo": "2026-06-30T08:00:00+00:00",
        },
    )
    excluded_legacy = _create_doc("旧无范围事件规则", "legacy unscoped 不能假装全局可用。")
    excluded_inactive = _create_doc(
        "已停用规则",
        "非 active 文档不能用于事件绑定知识。",
        {"regionId": "TEST_REGION_A", "roadId": "ROAD_A_PEOPLE", "eventType": "congestion"},
    )
    conn = sqlite3.connect(isolated["ragDb"])
    try:
        conn.execute(
            "UPDATE rag_documents SET status = 'draft' WHERE document_id = ?",
            (excluded_inactive["documentId"],),
        )
        conn.commit()
    finally:
        conn.close()
    _seed_region_b(repo)
    excluded_other_region = _create_doc(
        "其他区域规则",
        "其他区域规则不能进入人民路事件候选。",
        {"regionId": "TEST_REGION_B", "eventType": "congestion"},
    )
    excluded_global_type = _create_doc(
        "全局事故规则",
        "全局规则仍需匹配事件类型。",
        {"groundingScope": "GLOBAL", "eventType": "accident"},
    )

    from backend.rag.v2.document_repository import get_chunks_by_document
    from backend.rag.v2.sparse_index import search_sparse

    holdout_ids = {
        excluded_future["documentId"],
        excluded_expired["documentId"],
        excluded_other_region["documentId"],
        excluded_global_type["documentId"],
    }
    assert all(get_chunks_by_document(doc_id, active_only=True) for doc_id in holdout_ids)
    unrestricted = search_sparse("未来规则 到点过期规则 其他区域 全局事故", top_k=50)
    unrestricted_ids = {item["document_id"] for item in unrestricted}
    assert excluded_future["documentId"] in unrestricted_ids
    assert excluded_expired["documentId"] in unrestricted_ids

    from backend.knowledge.regional_context import EventKnowledgeContextService

    context = EventKnowledgeContextService(repo).get_context_for_event(
        "E_KNOW_ROAD",
        query="人民路拥堵处置",
        limit=20,
    )

    doc_ids = _evidence_doc_ids(context)
    assert include_road["documentId"] in doc_ids
    assert include_region["documentId"] in doc_ids
    assert include_global["documentId"] in doc_ids
    assert include_start_boundary["documentId"] in doc_ids
    assert include_historical_valid["documentId"] in doc_ids
    assert excluded_other_road["documentId"] not in doc_ids
    assert excluded_type["documentId"] not in doc_ids
    assert excluded_future["documentId"] not in doc_ids
    assert excluded_expired["documentId"] not in doc_ids
    assert excluded_inactive["documentId"] not in doc_ids
    assert excluded_legacy["documentId"] not in doc_ids
    assert excluded_other_region["documentId"] not in doc_ids
    assert excluded_global_type["documentId"] not in doc_ids
    assert context["scope"]["asOf"] == "2026-06-30T08:00:00+00:00"
    assert context["provenance"]["applicabilityFilter"] == "structured_pre_retrieval"
    assert context["provenance"]["connectedRoadExpansion"] is False
    assert context["provenance"]["retrievalPipeline"] == "rag_v2_hybrid_rrf_reranker"
    assert context["regionalGroundingStatus"] == "REGIONAL_GROUNDED"


def test_intersection_context_does_not_expand_to_connected_roads(isolated, repo):
    _seed_event("E_KNOW_INT", road_name="人民路-解放路路口")
    _bind_event(repo, "E_KNOW_INT", road_id=None, intersection_id="INT_A_PEOPLE_LIBERATION")

    include_intersection = _create_doc(
        "人民路解放路路口规则",
        "该路口拥堵时安排路口警力。",
        {
            "regionId": "TEST_REGION_A",
            "intersectionId": "INT_A_PEOPLE_LIBERATION",
            "eventType": "congestion",
        },
    )
    include_region = _create_doc(
        "区域路口拥堵规则",
        "区域拥堵时调配周边警力。",
        {"regionId": "TEST_REGION_A", "eventType": "congestion"},
    )
    excluded_connected_road = _create_doc(
        "连接道路规则",
        "道路级规则不能自动扩展到路口事件。",
        {"regionId": "TEST_REGION_A", "roadId": "ROAD_A_PEOPLE", "eventType": "congestion"},
    )

    from backend.knowledge.regional_context import EventKnowledgeContextService

    context = EventKnowledgeContextService(repo).get_context_for_event(
        "E_KNOW_INT",
        query="路口拥堵处置",
        limit=20,
    )
    doc_ids = _evidence_doc_ids(context)
    assert include_intersection["documentId"] in doc_ids
    assert include_region["documentId"] in doc_ids
    assert excluded_connected_road["documentId"] not in doc_ids


def test_unresolved_location_allows_only_explicit_global(isolated, repo):
    _seed_event("E_KNOW_UNRESOLVED", road_name="未知路段")
    global_doc = _create_doc(
        "显式全局证据规则",
        "无定位事件只可使用显式全局规则。",
        {"groundingScope": "GLOBAL", "eventType": "generic"},
    )
    legacy = _create_doc("旧无范围规则不应入选", "legacy unscoped 不是全局规则。")
    regional = _create_doc(
        "区域规则不应入选",
        "没有 binding 时不能猜测区域。",
        {"regionId": "TEST_REGION_A", "eventType": "congestion"},
    )

    from backend.knowledge.regional_context import EventKnowledgeContextService

    context = EventKnowledgeContextService(repo).get_context_for_event(
        "E_KNOW_UNRESOLVED",
        query="未知路段拥堵处置",
        limit=20,
    )
    doc_ids = _evidence_doc_ids(context)
    assert context["reason"] == "LOCATION_UNRESOLVED_GLOBAL_ONLY"
    assert context["regionalGroundingStatus"] == "GLOBAL_ONLY"
    assert global_doc["documentId"] in doc_ids
    assert legacy["documentId"] not in doc_ids
    assert regional["documentId"] not in doc_ids


def test_event_context_empty_and_invalid_asof_are_distinct(isolated, repo):
    _seed_event("E_KNOW_EMPTY")
    _bind_event(repo, "E_KNOW_EMPTY", road_id="ROAD_A_PEOPLE")
    _create_doc(
        "仅事故适用规则",
        "该规则只适用于事故。",
        {"regionId": "TEST_REGION_A", "roadId": "ROAD_A_PEOPLE", "eventType": "accident"},
    )

    from backend.knowledge.regional_context import EventKnowledgeContextService

    empty = EventKnowledgeContextService(repo).get_context_for_event(
        "E_KNOW_EMPTY",
        query="人民路拥堵处置",
    )
    assert empty["status"] == "ready"
    assert empty["evidenceState"] == "empty"
    assert empty["regionalGroundingStatus"] == "NO_APPLICABLE_EVIDENCE"

    _seed_event("E_KNOW_BAD_TIME")
    conn = sqlite3.connect(isolated["eventDb"])
    try:
        conn.execute("UPDATE event_records SET createdAt = 'not-a-time' WHERE eventId = ?", ("E_KNOW_BAD_TIME",))
        conn.commit()
    finally:
        conn.close()

    unavailable = EventKnowledgeContextService(repo).get_context_for_event("E_KNOW_BAD_TIME")
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"] == "INVALID_EVENT_CREATED_AT"
    assert unavailable["evidenceState"] == "unavailable"
    assert unavailable["regionalGroundingStatus"] == "UNAVAILABLE"


def test_event_context_api_returns_auditable_metadata(isolated, repo, api_client):
    _seed_event("E_KNOW_API")
    _bind_event(repo, "E_KNOW_API", road_id="ROAD_A_PEOPLE")
    created = _create_doc(
        "API人民路规则",
        "API 路径返回真实分块引用和区域元数据。",
        {
            "regionId": "TEST_REGION_A",
            "roadId": "ROAD_A_PEOPLE",
            "eventType": "congestion",
            "sourceUri": "manual://api-road",
        },
    )

    response = api_client.get("/knowledge/events/E_KNOW_API/context", params={"query": "人民路规则", "limit": 5})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["scope"]["regionId"] == "TEST_REGION_A"
    assert data["scope"]["roadId"] == "ROAD_A_PEOPLE"
    assert data["evidence"]
    assert created["documentId"] in _evidence_doc_ids(data)
    first = data["evidence"][0]
    assert first["chunkId"]
    assert first["regionalMetadata"]["regionId"] == "TEST_REGION_A"
    assert first["regionalMetadata"]["scopeMatch"] in {"road", "region", "global"}


def test_event_context_uses_hybrid_retriever_with_pre_ranking_restriction(
    isolated,
    monkeypatch,
):
    from backend.rag.v2.hybrid_retriever import HybridRetriever
    from backend.rag.v2.models import QueryAnalysis
    from backend.rag.v2.providers import FakeEmbeddingProvider

    captured = {}

    def fake_dense(query_embedding, top_k=30, where=None, collection_name=""):
        captured["denseWhere"] = where
        return [{
            "chunk_id": "c_allowed_dense",
            "document_id": "doc_allowed_a",
            "content": "allowed dense",
            "score": 0.9,
            "dense_rank": 1,
            "metadata": {"document_id": "doc_allowed_a"},
        }]

    def fake_sparse(query, top_k=30, doc_type=None, collection_name=None, allowed_document_ids=None):
        captured["sparseAllowed"] = sorted(allowed_document_ids or [])
        return [{
            "chunk_id": "c_allowed_sparse",
            "document_id": "doc_allowed_b",
            "content": "allowed sparse",
            "score": 0.8,
            "sparse_rank": 1,
            "metadata": {"document_id": "doc_allowed_b"},
        }]

    monkeypatch.setattr("backend.rag.v2.dense_index.is_available", lambda: True)
    monkeypatch.setattr("backend.rag.v2.dense_index.get_active_collection_name", lambda: "test_collection")
    monkeypatch.setattr("backend.rag.v2.dense_index.search_dense", fake_dense)
    monkeypatch.setattr("backend.rag.v2.sparse_index.search_sparse", fake_sparse)

    candidates = HybridRetriever(FakeEmbeddingProvider()).retrieve(
        "拥堵处置",
        analysis=QueryAnalysis(filters={}),
        top_k=10,
        allowed_document_ids=["doc_allowed_b", "doc_allowed_a"],
    )

    assert captured["denseWhere"] == {
        "document_id": {"$in": ["doc_allowed_a", "doc_allowed_b"]}
    }
    assert captured["sparseAllowed"] == ["doc_allowed_a", "doc_allowed_b"]
    assert {item["document_id"] for item in candidates} == {"doc_allowed_a", "doc_allowed_b"}


def test_dense_metadata_projection_without_real_chroma(monkeypatch):
    from backend.rag.v2 import dense_index
    from backend.rag.v2.models import RagChunk

    captured = {}

    class FakeCollection:
        def upsert(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(dense_index, "_CHROMA_AVAILABLE", True)
    monkeypatch.setattr(dense_index, "get_collection", lambda name: FakeCollection())

    chunk = RagChunk(
        chunk_id="chunk_scope_1",
        document_id="doc_scope_1",
        raw_content="人民路拥堵规则",
        contextual_content="人民路拥堵规则",
        chunk_index=0,
        region_id="TEST_REGION_A",
        road_id="ROAD_A_PEOPLE",
        intersection_id=None,
        grounding_scope="REGIONAL",
        event_type="congestion",
    )

    assert dense_index.upsert_chunks([chunk], [[0.1, 0.2]], "test_scope_collection")
    metadata = captured["metadatas"][0]
    assert metadata["region_id"] == "TEST_REGION_A"
    assert metadata["road_id"] == "ROAD_A_PEOPLE"
    assert metadata["intersection_id"] == ""
    assert metadata["grounding_scope"] == "REGIONAL"
