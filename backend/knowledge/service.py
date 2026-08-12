"""
Knowledge Service — Phase 16 Round 1

Wraps existing rag_v2 document_repository + IncrementalIndexer behind
a clean service layer for the Knowledge REST API.

All document state is canonical in SQLite (rag_v2.db). Chroma is a
retrieval index — always derivable from SQLite.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.rag.v2.document_repository import (
    create_index_job,
    delete_chunks_by_document,
    get_active_collection_name,
    get_chunks_by_document,
    get_document,
    get_latest_index_version,
    list_active_documents,
    soft_delete_document,
    update_index_job,
    upsert_chunks,
    upsert_document,
)
from backend.rag.v2.indexer import IncrementalIndexer, _checksum, _make_document_id
from backend.rag.v2.models import (
    AuthorityLevel,
    DocStatus,
    DocType,
    IndexJobResult,
    IndexJobStatus,
    IndexVersion,
    RagChunk,
    RagDocument,
    utcnow,
)
from backend.rag.v2.providers import get_embedding_provider
from backend.rag.v2.dense_index import get_collection, get_collection_count

logger = logging.getLogger("knowledge.service")

# ── Ingestion limits ──
MAX_CONTENT_LENGTH = 100_000  # 100KB
ALLOWED_DOC_TYPES = {DocType.RULE, DocType.DISPATCH_EXPERIENCE, DocType.EVENT_REPORT,
                     DocType.DAILY_REPORT, DocType.WEEKLY_REPORT, DocType.CASE,
                     DocType.REGULATION, DocType.AGENT_OUTPUT, DocType.OTHER}
MAX_NAME_LENGTH = 200


class KnowledgeError(Exception):
    """Knowledge service error with HTTP status hint."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ═══════════════════════════════════════════════════════════════════════════════
# Document Read
# ═══════════════════════════════════════════════════════════════════════════════

def list_documents(
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
) -> Dict[str, Any]:
    """列出文档（分页）。"""
    all_docs = list_active_documents()

    # ── Filter ──
    filtered = []
    for doc in all_docs:
        if not include_deleted and doc.status == DocStatus.DELETED:
            continue
        if status and doc.status != status:
            continue
        if doc_type and doc.doc_type != doc_type:
            continue
        filtered.append(doc)

    total = len(filtered)
    page = filtered[offset:offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "documents": [_doc_to_summary(d) for d in page],
    }


def get_document_detail(doc_id: str) -> Optional[Dict[str, Any]]:
    """获取文档详情（含 chunk 数量）。"""
    doc = get_document(doc_id)
    if doc is None:
        return None
    chunks = get_chunks_by_document(doc_id, active_only=True)
    return {
        "document": _doc_to_detail(doc),
        "chunkCount": len(chunks),
    }


def get_document_chunks(
    doc_id: str,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """获取文档的 chunks（分页）。"""
    doc = get_document(doc_id)
    if doc is None:
        return None
    all_chunks = get_chunks_by_document(doc_id, active_only=True)
    total = len(all_chunks)
    page = all_chunks[offset:offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "chunks": [_chunk_to_dto(c) for c in page],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Document Create / Ingest
# ═══════════════════════════════════════════════════════════════════════════════

def create_document(
    name: str,
    doc_type: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """创建并索引单个文档。

    流程: validate → checksum → register → chunk → embed → Chroma → status update
    """
    meta = metadata or {}

    # ── Validate ──
    name = (name or "").strip()
    if not name:
        raise KnowledgeError("文档名称不能为空")
    if len(name) > MAX_NAME_LENGTH:
        raise KnowledgeError(f"文档名称不能超过 {MAX_NAME_LENGTH} 字符")

    if not content or not content.strip():
        raise KnowledgeError("文档内容不能为空")
    if len(content) > MAX_CONTENT_LENGTH:
        raise KnowledgeError(f"文档内容不能超过 {MAX_CONTENT_LENGTH} 字符")

    try:
        dt = DocType(doc_type)
    except ValueError:
        raise KnowledgeError(f"不支持的文档类型 '{doc_type}'。有效值: {[t.value for t in ALLOWED_DOC_TYPES]}")

    if dt not in ALLOWED_DOC_TYPES:
        raise KnowledgeError(f"不支持的文档类型 '{doc_type}'")

    # ── Source ID + Document ID ──
    content_hash = _checksum(content)
    source_id = meta.get("source_id") or f"user:{uuid.uuid4().hex[:12]}"
    doc_id = _make_document_id(source_id)

    # ── Duplicate check ──
    existing = get_document(doc_id)
    if existing and existing.status != DocStatus.DELETED:
        if existing.checksum == content_hash:
            return _doc_to_summary(existing)  # idempotent: return existing
        # Content changed: will re-index below (version bump)

    # ── Register document (status=active initially, will be updated) ──
    now = utcnow()
    doc = RagDocument(
        document_id=doc_id,
        source_id=source_id,
        doc_type=dt,
        title=name,
        content=content,
        authority_level=AuthorityLevel(meta.get("authority_level", "operational")),
        version=(existing.version + 1) if existing else 1,
        status=DocStatus.ACTIVE,
        event_type=meta.get("event_type"),
        road_name=meta.get("road_name"),
        risk_level=meta.get("risk_level"),
        source_uri=meta.get("source_uri"),
        checksum=content_hash,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )

    # ── Persist document ──
    try:
        upsert_document(doc)
    except Exception as e:
        raise KnowledgeError(f"文档持久化失败: {e}", 500)

    # ── Chunk + Index ──
    try:
        _index_single_document(doc)
    except Exception as e:
        # Mark as failed but don't lose the document
        try:
            _mark_failed(doc_id, str(e))
        except Exception:
            pass
        raise KnowledgeError(f"文档索引失败: {e}", 500)

    return _doc_to_summary(get_document(doc_id) or doc)


def _index_single_document(doc: RagDocument) -> None:
    """Index a single document using IncrementalIndexer."""
    provider = get_embedding_provider()
    indexer = IncrementalIndexer(embedding_provider=provider)
    result = indexer.index_documents([doc])

    if result.status == IndexJobStatus.FAILED:
        errors = "; ".join(result.errors) if result.errors else "未知错误"
        raise KnowledgeError(f"索引失败: {errors}", 500)
    if result.status == IndexJobStatus.ROLLED_BACK:
        raise KnowledgeError("索引已回滚", 500)


def _mark_failed(doc_id: str, error_msg: str) -> None:
    """标记文档为索引失败（区分于用户删除）。"""
    import sqlite3
    from backend.rag.v2.config import RAG_V2_DB_PATH
    conn = sqlite3.connect(RAG_V2_DB_PATH)
    conn.execute(
        "UPDATE rag_documents SET status='failed', source_uri=?, updated_at=? WHERE document_id=?",
        (f"error:{error_msg[:500]}", utcnow().isoformat(), doc_id),
    )
    conn.commit()
    conn.close()
    logger.error(f"Document {doc_id} indexing failed: {error_msg}")


# ═══════════════════════════════════════════════════════════════════════════════
# Document Delete
# ═══════════════════════════════════════════════════════════════════════════════

def delete_document(doc_id: str) -> Dict[str, str]:
    """软删除文档及其 chunks/vectors。"""
    doc = get_document(doc_id)
    if doc is None:
        raise KnowledgeError(f"文档 '{doc_id}' 不存在", 404)
    if doc.status == DocStatus.DELETED:
        # Already deleted — idempotent
        return {"documentId": doc_id, "status": "deleted"}

    # Soft-delete in SQLite
    soft_delete_document(doc_id)
    delete_chunks_by_document(doc_id)

    # Delete from Chroma
    try:
        from backend.rag.v2.dense_index import delete_by_document
        delete_by_document(doc_id)
    except Exception as e:
        logger.warning(f"Failed to delete Chroma vectors for {doc_id}: {e}")
        # Non-fatal: SQLite is canonical

    return {"documentId": doc_id, "status": "deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
# Single Document Reindex
# ═══════════════════════════════════════════════════════════════════════════════

def reindex_document(doc_id: str) -> Dict[str, Any]:
    """重新索引单个文档（幂等：content hash 不变则跳过）。"""
    doc = get_document(doc_id)
    if doc is None:
        raise KnowledgeError(f"文档 '{doc_id}' 不存在", 404)
    if doc.status == DocStatus.DELETED:
        raise KnowledgeError(f"已删除的文档无法重建索引", 400)

    if not doc.content:
        raise KnowledgeError(f"文档内容为空，无法重建索引", 400)

    try:
        _index_single_document(doc)
    except Exception as e:
        raise KnowledgeError(f"重建索引失败: {e}", 500)

    return _doc_to_summary(get_document(doc_id) or doc)


# ═══════════════════════════════════════════════════════════════════════════════
# Index Status
# ═══════════════════════════════════════════════════════════════════════════════

def get_index_status() -> Dict[str, Any]:
    """获取索引状态（只读）。"""
    active = get_latest_index_version()
    provider = get_embedding_provider()

    # Count active documents and chunks
    all_docs = list_active_documents()
    active_docs = [d for d in all_docs if d.status != DocStatus.DELETED]
    doc_count = len(active_docs)

    chunk_count = 0
    for d in active_docs:
        chunks = get_chunks_by_document(d.document_id, active_only=True)
        chunk_count += len(chunks)

    # Chroma vector count
    vector_count = None
    collection_name = None
    if active and active.collection_name:
        collection_name = active.collection_name
        try:
            vector_count = get_collection_count(active.collection_name)
        except Exception:
            pass

    is_healthy = (
        active is not None
        and active.status == "active"
        and collection_name is not None
        and vector_count is not None
        and vector_count > 0
        and active.embedding_model
        and "fake" not in active.embedding_model.lower()
    )

    return {
        "activeIndexVersion": active.version_id if active else None,
        "collectionName": collection_name,
        "embeddingModel": active.embedding_model if active else None,
        "embeddingDimension": active.embedding_dimension if active else None,
        "documentCount": doc_count,
        "chunkCount": chunk_count,
        "vectorCount": vector_count,
        "status": active.status if active else "no_index",
        "lastIndexedAt": active.committed_at.isoformat() if active and active.committed_at else None,
        "healthy": is_healthy,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Consistency Check
# ═══════════════════════════════════════════════════════════════════════════════

def check_consistency() -> Dict[str, Any]:
    """检查 SQLite ↔ Chroma 一致性（只读）。"""
    issues: List[str] = []

    # 1. Active index version exists
    active = get_latest_index_version()
    if not active:
        return {"healthy": False, "issues": ["没有活跃的索引版本"]}

    # 2. Active collection exists
    collection_name = active.collection_name
    if not collection_name:
        issues.append("活跃索引版本没有关联 collection")
        return {"healthy": False, "issues": issues}

    # 3. Embedding dimension matches
    provider = get_embedding_provider()
    resolved_dim = provider.get_dimension()
    if active.embedding_dimension and active.embedding_dimension != resolved_dim:
        issues.append(
            f"维度不匹配: index={active.embedding_dimension} provider={resolved_dim}"
        )

    # 4. Collection is not fake/test
    is_fake = "fake" in active.embedding_model.lower() if active.embedding_model else False
    if is_fake:
        issues.append(
            f"活跃索引使用测试模型: {active.embedding_model}。"
            f"运行 POST /rag/v2/index 修复。"
        )

    # 5. SQLite active chunk count
    all_docs = list_active_documents()
    active_docs = [d for d in all_docs if d.status != DocStatus.DELETED]
    sqlite_chunks = 0
    for d in active_docs:
        chunks = get_chunks_by_document(d.document_id, active_only=True)
        sqlite_chunks += len(chunks)

    # 6. Chroma vector count
    try:
        chroma_count = get_collection_count(collection_name)
    except Exception:
        chroma_count = None
        issues.append(f"无法查询 Chroma collection '{collection_name}'")

    if chroma_count is None:
        issues.append("无法获取 Chroma vector 数量")
    elif sqlite_chunks != chroma_count:
        issues.append(
            f"SQLite chunks ({sqlite_chunks}) 与 Chroma vectors ({chroma_count}) 不一致"
        )

    # 7. Orphan vectors / missing vectors
    if chroma_count is not None and sqlite_chunks < (chroma_count or 0):
        issues.append(f"可能存在 orphan vectors: Chroma ({chroma_count}) > SQLite ({sqlite_chunks})")
    elif chroma_count is not None and sqlite_chunks > (chroma_count or 0):
        issues.append(f"可能存在缺失 vectors: SQLite ({sqlite_chunks}) > Chroma ({chroma_count})")

    return {
        "healthy": len(issues) == 0,
        "issues": issues,
        "details": {
            "activeIndexVersion": active.version_id,
            "collectionName": collection_name,
            "embeddingModel": active.embedding_model,
            "embeddingDimension": active.embedding_dimension,
            "sqliteChunkCount": sqlite_chunks,
            "chromaVectorCount": chroma_count,
            "isFakeCollection": is_fake,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DTO helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _doc_to_summary(doc: RagDocument) -> Dict[str, Any]:
    """Document → list summary DTO."""
    chunks = get_chunks_by_document(doc.document_id, active_only=True)
    # Extract error message if status is failed (stored in source_uri)
    error_message = None
    if doc.status == DocStatus.FAILED and doc.source_uri and doc.source_uri.startswith("error:"):
        error_message = doc.source_uri[6:]  # Strip "error:" prefix
    return {
        "documentId": doc.document_id,
        "name": doc.title,
        "sourceId": doc.source_id,
        "docType": doc.doc_type,
        "authorityLevel": doc.authority_level,
        "status": doc.status,
        "contentHash": doc.checksum,
        "version": doc.version,
        "chunkCount": len(chunks),
        "createdAt": doc.created_at.isoformat() if doc.created_at else None,
        "updatedAt": doc.updated_at.isoformat() if doc.updated_at else None,
        "sourceUri": doc.source_uri if (not doc.source_uri or not doc.source_uri.startswith("error:")) else None,
        "eventType": doc.event_type,
        "roadName": doc.road_name,
        "errorMessage": error_message,
    }


def _doc_to_detail(doc: RagDocument) -> Dict[str, Any]:
    """Document → detail DTO."""
    return {
        **_doc_to_summary(doc),
        "content": doc.content,
        "effectiveFrom": doc.effective_from.isoformat() if doc.effective_from else None,
        "effectiveTo": doc.effective_to.isoformat() if doc.effective_to else None,
        "jurisdiction": doc.jurisdiction,
        "riskLevel": doc.risk_level,
    }


def _chunk_to_dto(chunk: RagChunk) -> Dict[str, Any]:
    """Chunk → DTO (no embedding vector)."""
    return {
        "chunkId": chunk.chunk_id,
        "documentId": chunk.document_id,
        "chunkIndex": chunk.chunk_index,
        "sectionPath": chunk.section_path,
        "content": chunk.raw_content,
        "contentHash": chunk.checksum,
        "docType": chunk.doc_type,
        "authorityLevel": chunk.authority_level,
        "createdAt": chunk.created_at.isoformat() if chunk.created_at else None,
    }
