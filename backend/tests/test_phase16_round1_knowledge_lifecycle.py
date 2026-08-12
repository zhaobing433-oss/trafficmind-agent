"""
Phase 16 Round 1 — Knowledge Lifecycle Backend Tests

Tests for the Knowledge REST API:
  - Document CRUD (list, detail, create, delete)
  - Chunks (list, pagination)
  - Reindex (single document)
  - Index status + consistency check
  - Test isolation (never mutates production DB)
  - Failure paths (empty, oversized, invalid type, missing)
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Generator

import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures — all tests use ISOLATED temp DBs, never production
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _isolate_knowledge_db(monkeypatch):
    """All tests use isolated temp DB + FakeEmbeddingProvider + temp Chroma.

    The production DB and Chroma are NEVER touched.
    """
    import backend.rag.v2.config as v2_config
    import backend.rag.v2.document_repository as doc_repo
    from backend.rag.v2.providers import FakeEmbeddingProvider

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "rag_v2_test.db")
        chroma_path = os.path.join(tmpdir, "test_chroma")

        # Isolate SQLite
        monkeypatch.setattr(v2_config, "RAG_V2_DB_PATH", db_path)
        monkeypatch.setattr(doc_repo, "RAG_V2_DB_PATH", db_path)

        # Isolate Chroma directory
        import backend.rag.v2.dense_index as dense_idx
        dense_idx._VECTOR_DB_PATH = chroma_path
        monkeypatch.setattr(dense_idx, "_get_vector_db_path", lambda: chroma_path)

        # Use fake embedding provider (no model download)
        fake_provider = FakeEmbeddingProvider(dimension=384)
        monkeypatch.setattr(
            "backend.rag.v2.providers.get_embedding_provider",
            lambda: fake_provider
        )
        monkeypatch.setattr(
            "backend.knowledge.service.get_embedding_provider",
            lambda: fake_provider
        )

        doc_repo.init_db()
        yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient."""
    from backend.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_content() -> str:
    return """## 拥堵处置预案

### 判定条件
- 平均速度 < 20 km/h
- 排队长度 > 100 米

### 处置措施
1. 通知辖区交警前往现场疏导
2. 协调上游路口信号配时调整
3. 通过诱导屏引导车辆绕行
4. 持续监测排队长度和平均速度变化

### 恢复条件
- 平均速度恢复至 30 km/h 以上
- 排队长度降至 50 米以下
- 持续 10 分钟以上
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Document List
# ═══════════════════════════════════════════════════════════════════════════════

class TestDocumentList:
    def test_empty_list(self, client):
        resp = client.get("/knowledge/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["documents"] == []

    def test_list_with_docs(self, client, sample_content):
        # Create a doc first
        client.post("/knowledge/documents", json={
            "name": "拥堵处置预案", "docType": "rule", "content": sample_content,
        })
        resp = client.get("/knowledge/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["documents"]) >= 1

    def test_pagination(self, client, sample_content):
        # Create 3 docs
        for i in range(3):
            client.post("/knowledge/documents", json={
                "name": f"测试文档{i}", "docType": "rule",
                "content": f"## 测试内容 {i}\n\n测试正文{i}",
            })
        resp = client.get("/knowledge/documents?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["documents"]) <= 2
        assert data["total"] >= 3

        # Page 2
        resp2 = client.get("/knowledge/documents?limit=2&offset=2")
        assert resp2.status_code == 200

        # Verify no overlap
        ids1 = {d["documentId"] for d in data["documents"]}
        ids2 = {d["documentId"] for d in resp2.json()["documents"]}
        assert ids1.isdisjoint(ids2)

    def test_status_filter(self, client, sample_content):
        client.post("/knowledge/documents", json={
            "name": "测试", "docType": "rule", "content": sample_content,
        })
        resp = client.get("/knowledge/documents?status=active")
        assert resp.status_code == 200
        for d in resp.json()["documents"]:
            assert d["status"] == "active"

    def test_doc_type_filter(self, client, sample_content):
        client.post("/knowledge/documents", json={
            "name": "规则文档", "docType": "rule", "content": sample_content,
        })
        resp = client.get("/knowledge/documents?doc_type=rule")
        assert resp.status_code == 200
        for d in resp.json()["documents"]:
            assert d["docType"] == "rule"

    def test_include_deleted(self, client, sample_content):
        # Create then delete
        r = client.post("/knowledge/documents", json={
            "name": "待删除", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        client.delete(f"/knowledge/documents/{doc_id}")

        # Default: excluded
        resp = client.get("/knowledge/documents")
        ids = {d["documentId"] for d in resp.json()["documents"]}
        assert doc_id not in ids

        # With include_deleted: included
        resp2 = client.get("/knowledge/documents?include_deleted=true")
        ids2 = {d["documentId"] for d in resp2.json()["documents"]}
        assert doc_id in ids2

    def test_document_summary_fields(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "字段测试", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        resp = client.get("/knowledge/documents")
        docs = resp.json()["documents"]
        target = next(d for d in docs if d["documentId"] == doc_id)

        assert "documentId" in target
        assert "name" in target
        assert "docType" in target
        assert "status" in target
        assert "contentHash" in target
        assert "chunkCount" in target
        assert "createdAt" in target
        assert "updatedAt" in target
        assert target["name"] == "字段测试"


# ═══════════════════════════════════════════════════════════════════════════════
# Document Detail
# ═══════════════════════════════════════════════════════════════════════════════

class TestDocumentDetail:
    def test_detail(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "详情测试", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        resp = client.get(f"/knowledge/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "document" in data
        assert "chunkCount" in data
        assert data["document"]["name"] == "详情测试"
        assert "content" in data["document"]

    def test_nonexistent_404(self, client):
        resp = client.get("/knowledge/documents/nonexistent_id_12345")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Document Create
# ═══════════════════════════════════════════════════════════════════════════════

class TestDocumentCreate:
    def test_create_markdown(self, client, sample_content):
        resp = client.post("/knowledge/documents", json={
            "name": "拥堵处置预案", "docType": "rule", "content": sample_content,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "拥堵处置预案"
        assert data["docType"] == "rule"
        assert data["status"] == "active"
        assert data["contentHash"]
        assert data["chunkCount"] > 0

    def test_create_txt(self, client):
        content = "This is a plain text document about traffic signal management."
        resp = client.post("/knowledge/documents", json={
            "name": "信号管理", "docType": "dispatch_experience", "content": content,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_empty_content_reject(self, client):
        resp = client.post("/knowledge/documents", json={
            "name": "空文档", "docType": "rule", "content": "",
        })
        assert resp.status_code == 400

    def test_whitespace_only_reject(self, client):
        resp = client.post("/knowledge/documents", json={
            "name": "空白文档", "docType": "rule", "content": "   \n  \n  ",
        })
        assert resp.status_code == 400

    def test_empty_name_reject(self, client):
        resp = client.post("/knowledge/documents", json={
            "name": "", "docType": "rule", "content": "valid content",
        })
        assert resp.status_code == 400

    def test_oversized_content_reject(self, client):
        big_content = "x" * 200_000
        resp = client.post("/knowledge/documents", json={
            "name": "超大文档", "docType": "rule", "content": big_content,
        })
        assert resp.status_code == 400

    def test_unsupported_type_reject(self, client):
        resp = client.post("/knowledge/documents", json={
            "name": "PDF文档", "docType": "pdf", "content": "some content",
        })
        assert resp.status_code == 400

    def test_duplicate_content_idempotent(self, client, sample_content):
        r1 = client.post("/knowledge/documents", json={
            "name": "去重测试", "docType": "rule", "content": sample_content,
        })
        r2 = client.post("/knowledge/documents", json={
            "name": "去重测试", "docType": "rule", "content": sample_content,
            "metadata": {"source_id": r1.json().get("sourceId")},
        })
        # Same source_id + same content → returns existing
        assert r2.status_code == 200

    def test_create_with_metadata(self, client, sample_content):
        resp = client.post("/knowledge/documents", json={
            "name": "带元数据", "docType": "rule", "content": sample_content,
            "metadata": {
                "event_type": "congestion",
                "road_name": "测试路",
                "authority_level": "official",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"

    def test_long_name_reject(self, client):
        resp = client.post("/knowledge/documents", json={
            "name": "x" * 300, "docType": "rule", "content": "valid",
        })
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Document Delete
# ═══════════════════════════════════════════════════════════════════════════════

class TestDocumentDelete:
    def test_soft_delete(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "待删除", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        resp = client.delete(f"/knowledge/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_deleted_not_in_list(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "将删除", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        client.delete(f"/knowledge/documents/{doc_id}")

        resp = client.get("/knowledge/documents")
        ids = {d["documentId"] for d in resp.json()["documents"]}
        assert doc_id not in ids

    def test_repeated_delete_idempotent(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "重复删", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        client.delete(f"/knowledge/documents/{doc_id}")
        resp2 = client.delete(f"/knowledge/documents/{doc_id}")
        assert resp2.status_code == 200

    def test_delete_nonexistent_404(self, client):
        resp = client.delete("/knowledge/documents/does_not_exist_xyz")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Chunks
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunks:
    def test_list_chunks(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "分块测试", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        resp = client.get(f"/knowledge/documents/{doc_id}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert len(data["chunks"]) > 0
        chunk = data["chunks"][0]
        assert "chunkId" in chunk
        assert "documentId" in chunk
        assert "chunkIndex" in chunk
        assert "content" in chunk
        assert "contentHash" in chunk
        # No embedding vector exposed
        assert "embedding" not in chunk

    def test_chunk_pagination(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "分页块", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        resp = client.get(f"/knowledge/documents/{doc_id}/chunks?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 1

    def test_chunks_nonexistent_doc(self, client):
        resp = client.get("/knowledge/documents/nonexistent_xyz/chunks")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Reindex
# ═══════════════════════════════════════════════════════════════════════════════

class TestReindex:
    def test_reindex_single_doc(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "重建索引", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        resp = client.post(f"/knowledge/documents/{doc_id}/reindex")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_reindex_idempotent(self, client, sample_content):
        r = client.post("/knowledge/documents", json={
            "name": "幂等重索引", "docType": "rule", "content": sample_content,
        })
        doc_id = r.json()["documentId"]
        client.post(f"/knowledge/documents/{doc_id}/reindex")
        resp2 = client.post(f"/knowledge/documents/{doc_id}/reindex")
        assert resp2.status_code == 200

    def test_reindex_nonexistent(self, client):
        resp = client.post("/knowledge/documents/nonexistent_xyz/reindex")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Index Status + Consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestIndexStatus:
    def test_index_status_returns(self, client):
        resp = client.get("/knowledge/index/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "healthy" in data
        assert "documentCount" in data
        assert "chunkCount" in data

    def test_consistency_check(self, client):
        resp = client.get("/knowledge/index/consistency")
        assert resp.status_code == 200
        data = resp.json()
        assert "healthy" in data
        assert "issues" in data

    def test_consistency_after_create(self, client, sample_content):
        client.post("/knowledge/documents", json={
            "name": "一致性测试", "docType": "rule", "content": sample_content,
        })
        resp = client.get("/knowledge/index/consistency")
        assert resp.status_code == 200

    def test_status_readonly(self, client):
        """Index status is read-only — repeated calls don't change data."""
        r1 = client.get("/knowledge/index/status")
        r2 = client.get("/knowledge/index/status")
        assert r1.json() == r2.json()


# ═══════════════════════════════════════════════════════════════════════════════
# Validation / Security
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidation:
    def test_missing_required_fields(self, client):
        resp = client.post("/knowledge/documents", json={})
        assert resp.status_code == 422  # Pydantic validation

    def test_invalid_json(self, client):
        resp = client.post("/knowledge/documents",
                           content="not json",
                           headers={"Content-Type": "application/json"})
        assert resp.status_code in (400, 422)

    def test_get_endpoint_readonly(self, client):
        """GET endpoints don't mutate."""
        r1 = client.get("/knowledge/documents")
        r2 = client.get("/knowledge/documents")
        assert r1.json()["total"] == r2.json()["total"]


# ═══════════════════════════════════════════════════════════════════════════════
# Test Isolation Verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsolation:
    def test_does_not_mutate_production_db(self):
        """Verify production RAG V2 DB path exists but tests use temp DB."""
        import backend.rag.v2.config as v2_config
        prod_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "rag_v2", "rag_v2.db"
        )
        # The monkeypatched path should NOT be the production path
        assert v2_config.RAG_V2_DB_PATH != prod_path or not os.path.exists(prod_path), (
            "Test is using production RAG V2 DB! Isolation failure."
        )

    def test_isolated_db_starts_empty(self, client):
        resp = client.get("/knowledge/documents")
        assert resp.json()["total"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Error / Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_special_characters_in_name(self, client, sample_content):
        resp = client.post("/knowledge/documents", json={
            "name": "测试 - 拥堵 · 事故 (2024版)",
            "docType": "rule",
            "content": sample_content,
        })
        assert resp.status_code == 200

    def test_unicode_content(self, client):
        content = "中文交通规则：\n1. 限速规则\n2. 信号规则\n3. 事故处理规程"
        resp = client.post("/knowledge/documents", json={
            "name": "中文测试", "docType": "rule", "content": content,
        })
        assert resp.status_code == 200
