"""
RAG V2 Dense Index — ChromaDB with explicit embeddings passed by caller.

CRITICAL: Embeddings are ALWAYS passed explicitly via `embeddings` parameter.
We NEVER rely on Chroma's built-in embedding function.
"""
from __future__ import annotations
import logging
import os
import re
from typing import Dict, List, Optional

from backend.rag.v2.config import RAG_V2_COLLECTION_NAME, RAG_V2_V1_COLLECTION_NAME
from backend.rag.v2.models import RagChunk

logger = logging.getLogger("rag.v2.dense_index")

# Legacy V1 collection name — must never be deleted
V1_COLLECTION_NAME = RAG_V2_V1_COLLECTION_NAME

_CHROMA_AVAILABLE = False
try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    pass

_VECTOR_DB_PATH: Optional[str] = None


def _get_vector_db_path() -> str:
    global _VECTOR_DB_PATH
    if _VECTOR_DB_PATH is None:
        from pathlib import Path
        _backend = Path(__file__).resolve().parent.parent.parent
        _VECTOR_DB_PATH = str(_backend / "data" / "vector_db")
    return _VECTOR_DB_PATH


def is_available() -> bool:
    return _CHROMA_AVAILABLE


def get_client() -> Optional[object]:
    """获取 ChromaDB 客户端。"""
    if not _CHROMA_AVAILABLE:
        return None
    import chromadb
    os.makedirs(_get_vector_db_path(), exist_ok=True)
    return chromadb.PersistentClient(path=_get_vector_db_path())


def get_collection(name: str = RAG_V2_COLLECTION_NAME) -> Optional[object]:
    """获取或创建 collection（不含默认 embedding function）。

    注意：不设置 embedding_function，因为所有 embeddings 由调用方显式传入。
    """
    if not _CHROMA_AVAILABLE:
        return None
    try:
        client = get_client()
        if client is None:
            return None
        # Use None embedding function — we pass embeddings explicitly
        return client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,  # EXPLICIT: no default embedder
        )
    except Exception as e:
        logger.error(f"Failed to get collection '{name}': {e}")
        return None


# ─── Versioned collection helpers ────────────────────────────────────────────

def _sanitize_model_name(model_name: str) -> str:
    """Extract a short safe model identifier from a model name for collection naming.

    "Qwen/Qwen3-Embedding-0.6B" → "qwen3"
    "BAAI/bge-large-zh" → "bge"
    "text-embedding-ada-002" → "text"
    """
    # Take segment after last /
    short = model_name.rsplit("/", 1)[-1] if "/" in model_name else model_name
    # Take first dash-delimited component (the family name)
    short = short.split("-")[0].split("_")[0]
    short = re.sub(r'[^a-zA-Z0-9]', '', short).lower()
    return short[:24] or "model"


def make_versioned_collection_name(model_name: str, dimension: int) -> str:
    """生成版本化 collection 名称。

    e.g. "trafficmind_knowledge_v2_qwen3_1024"
    Never uses the base name alone — always versioned.
    """
    short = _sanitize_model_name(model_name)
    return f"{RAG_V2_COLLECTION_NAME}_{short}_{dimension}"


def get_or_create_collection_for_model(model_name: str, dimension: int) -> str:
    """获取或创建指定 embedding 模型对应的版本化 collection。

    Returns:
        collection 名称
    """
    name = make_versioned_collection_name(model_name, dimension)
    get_collection(name)  # creates if not exists
    logger.info(f"Versioned collection ready: {name} (model={model_name}, dim={dimension})")
    return name


def get_active_collection_name() -> str:
    """读取当前活跃的版本化 collection 名称（从 rag_index_versions）。

    如果活跃 collection 与当前 resolved provider 不兼容，返回 None 以阻止查询。
    """
    from backend.rag.v2.document_repository import get_latest_index_version
    from backend.rag.v2.providers import get_embedding_provider
    active = get_latest_index_version()
    if not active or not active.collection_name:
        return RAG_V2_COLLECTION_NAME

    # Check compatibility with current provider
    emb = get_embedding_provider()
    resolved_name = emb.get_resolved_model_name()
    resolved_dim = emb.get_dimension()

    if active.embedding_model and active.embedding_dimension:
        expected = make_versioned_collection_name(resolved_name, resolved_dim)
        if active.collection_name != expected:
            logger.warning(
                f"Active collection '{active.collection_name}' "
                f"(model={active.embedding_model}, dim={active.embedding_dimension}) "
                f"is INCOMPATIBLE with current provider "
                f"(model={resolved_name}, dim={resolved_dim}). "
                f"Expected collection: '{expected}'. "
                f"Run POST /rag/v2/index to rebuild."
            )
            # Return empty string to signal incompatibility — caller must handle
            return ""

    return active.collection_name


def set_active_collection_name(collection_name: str) -> bool:
    """将指定 collection 的版本设为活跃。

    Finds the latest index version for this collection name and marks it active.
    Previous active versions are superseded.
    """
    from backend.rag.v2.document_repository import (
        _get_conn,
        commit_index_version,
    )
    conn = _get_conn()
    row = conn.execute(
        "SELECT version_id, document_count, chunk_count FROM rag_index_versions "
        "WHERE collection_name=? ORDER BY committed_at DESC LIMIT 1",
        (collection_name,),
    ).fetchone()
    conn.close()
    if row is None:
        logger.warning(f"Cannot set active: no index version found for collection '{collection_name}'")
        return False
    r = dict(row)
    commit_index_version(r["version_id"], r["document_count"], r["chunk_count"])
    logger.info(f"Active collection set to: {collection_name}")
    return True


def check_compatibility(model_name: str, dimension: int) -> str:
    """检查指定模型/维度与当前活跃 collection 是否兼容。

    Returns:
        "ok" — 兼容，可增量索引
        "new" — 尚无活跃版本，需创建新 collection
        "incompatible" — 模型或维度变化，需新 collection + 全量重建
    """
    from backend.rag.v2.document_repository import get_latest_index_version
    active = get_latest_index_version()
    if active is None or active.status != "active":
        return "new"

    # Legacy version without model info — assume compatible, continue incremental
    if not active.embedding_model and not active.embedding_dimension:
        return "ok"

    # Compare via expected versioned collection name
    expected = make_versioned_collection_name(model_name, dimension)
    if active.collection_name == expected:
        return "ok"
    return "incompatible"


def upsert_chunks(
    chunks: List[RagChunk],
    embeddings: List[List[float]],
    collection_name: str = RAG_V2_COLLECTION_NAME,
) -> bool:
    """显式传入 embeddings 写入 Chroma。

    Args:
        chunks: RagChunk 列表
        embeddings: 与 chunks 一一对应的向量
        collection_name: Collection 名称

    Returns:
        是否成功
    """
    if not _CHROMA_AVAILABLE:
        logger.warning("ChromaDB not available")
        return False
    if len(chunks) != len(embeddings):
        raise ValueError(f"chunks ({len(chunks)}) vs embeddings ({len(embeddings)}) count mismatch")
    if not chunks:
        return True

    col = get_collection(collection_name)
    if col is None:
        return False

    ids = [c.chunk_id for c in chunks]
    documents = [c.contextual_content for c in chunks]
    metadatas = [
        {
            "document_id": c.document_id,
            "parent_chunk_id": c.parent_chunk_id or "",
            "section_path": c.section_path[:500],
            "doc_type": c.doc_type,
            "event_type": c.event_type or "",
            "road_name": c.road_name or "",
            "risk_level": c.risk_level or "",
            "authority_level": c.authority_level,
            "version": c.version,
            "chunk_index": c.chunk_index,
            "effective_from": c.effective_from.isoformat() if c.effective_from else "",
            "effective_to": c.effective_to.isoformat() if c.effective_to else "",
            "region_id": c.region_id or "",
            "road_id": c.road_id or "",
            "intersection_id": c.intersection_id or "",
            "grounding_scope": c.grounding_scope or "LEGACY_UNSCOPED",
        }
        for c in chunks
    ]

    try:
        col.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        logger.info(f"Dense upsert: {len(chunks)} chunks → {collection_name}")
        return True
    except Exception as e:
        logger.error(f"Dense upsert failed: {e}")
        return False


def delete_by_document(doc_id: str, collection_name: str = RAG_V2_COLLECTION_NAME) -> bool:
    """删除文档的所有 chunks。"""
    col = get_collection(collection_name)
    if col is None:
        return False
    try:
        # Chroma doesn't support delete by metadata filter directly in all versions
        # We do a get + delete by ids
        results = col.get(where={"document_id": doc_id})
        if results and results.get("ids"):
            col.delete(ids=results["ids"])
            logger.info(f"Dense delete: {len(results['ids'])} chunks for doc {doc_id}")
        return True
    except Exception as e:
        logger.error(f"Dense delete failed for {doc_id}: {e}")
        return False


def search_dense(
    query_embedding: List[float],
    top_k: int = 30,
    where: Optional[Dict] = None,
    collection_name: str = RAG_V2_COLLECTION_NAME,
) -> List[Dict]:
    """显式传入 query_embedding 执行向量检索。

    Args:
        query_embedding: 查询向量（由调用方显式传入）
        top_k: 返回数量
        where: Chroma metadata filter
        collection_name: Collection 名称

    Returns:
        [{chunk_id, document_id, content, score, metadata, rank}, ...]
    """
    if not query_embedding:
        return []

    col = get_collection(collection_name)
    if col is None:
        return []

    # Check if collection has data
    try:
        if col.count() == 0:
            return []
    except Exception:
        return []

    try:
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.error(f"Dense search failed: {e}")
        return []

    if not results.get("ids") or not results["ids"][0]:
        return []

    out = []
    for i in range(len(results["ids"][0])):
        dist = results["distances"][0][i]
        # Cosine distance → similarity score
        score = round(1.0 - dist, 6)
        meta = results["metadatas"][0][i] if results.get("metadatas") else {}
        out.append({
            "chunk_id": results["ids"][0][i],
            "document_id": meta.get("document_id", ""),
            "parent_chunk_id": meta.get("parent_chunk_id", ""),
            "content": results["documents"][0][i] if results.get("documents") else "",
            "score": score,
            "metadata": meta,
            "dense_rank": i + 1,
            "channel": "dense",
        })
    return out


def get_collection_count(collection_name: str = RAG_V2_COLLECTION_NAME) -> int:
    """获取 collection 中的 chunk 数量。"""
    col = get_collection(collection_name)
    if col is None:
        return 0
    try:
        return col.count()
    except Exception:
        return 0
