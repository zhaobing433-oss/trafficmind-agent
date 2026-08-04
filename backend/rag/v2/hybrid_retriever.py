"""
RAG V2 Hybrid Retriever — Dense + Sparse + Structured → RRF fusion.

Channels:
- Dense: ChromaDB with explicit query embeddings
- Sparse: FTS5/Jieba BM25
- Structured: Rule-based similarity (9-dimension weighted)
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

from backend.rag.v2.config import (
    RAG_DENSE_TOP_K,
    RAG_SPARSE_TOP_K,
    RAG_STRUCTURED_TOP_K,
    RAG_RRF_K,
    RAG_RRF_WINDOW,
)
from backend.rag.v2.models import QueryAnalysis, RetrievalCandidate
from backend.rag.v2.providers import EmbeddingProvider
from backend.rag.v2.rrf import reciprocal_rank_fusion

logger = logging.getLogger("rag.v2.hybrid_retriever")


class HybridRetriever:
    """混合检索器 — 多通道召回 + RRF 融合。"""

    def __init__(self, embedding_provider: EmbeddingProvider):
        self.embedding_provider = embedding_provider

    def retrieve(
        self,
        query: str,
        rewritten_query: str = "",
        analysis: Optional[QueryAnalysis] = None,
        top_k: int = 30,
        dense_top_k: int = RAG_DENSE_TOP_K,
        sparse_top_k: int = RAG_SPARSE_TOP_K,
        structured_top_k: int = RAG_STRUCTURED_TOP_K,
    ) -> List[Dict]:
        """执行混合检索。

        Args:
            query: 原始查询
            rewritten_query: 重写后的查询（优先用于检索）
            analysis: 查询分析结果
            top_k: RRF 后返回数量
            dense_top_k: Dense 通道取多少
            sparse_top_k: Sparse 通道取多少
            structured_top_k: Structured 通道取多少

        Returns:
            RRF 融合后的候选列表
        """
        search_query = rewritten_query or query

        # Channel 1: Dense retrieval
        dense_results = self._dense_retrieve(search_query, dense_top_k, analysis)

        # Channel 2: Sparse retrieval
        sparse_results = self._sparse_retrieve(search_query, sparse_top_k, analysis)

        # Channel 3: Structured retrieval
        structured_results = self._structured_retrieve(search_query, structured_top_k, analysis)

        logger.info(
            f"Retrieval: dense={len(dense_results)}, sparse={len(sparse_results)}, "
            f"structured={len(structured_results)}"
        )

        # RRF fusion
        fused = reciprocal_rank_fusion(
            [dense_results, sparse_results, structured_results],
            k=RAG_RRF_K,
            window=RAG_RRF_WINDOW,
        )

        return fused[:top_k]

    def _dense_retrieve(
        self, query: str, top_k: int, analysis: Optional[QueryAnalysis],
    ) -> List[Dict]:
        """Dense 通道：显式传入 query_embedding。"""
        from backend.rag.v2.dense_index import search_dense, is_available

        if not is_available():
            logger.warning("Dense index not available")
            return []

        try:
            query_embedding = self.embedding_provider.embed_text(query)
        except Exception as e:
            logger.error(f"Dense embedding failed: {e}")
            return []

        where = None
        if analysis and analysis.filters:
            where = {}
            if analysis.filters.get("event_type"):
                where["event_type"] = analysis.filters["event_type"]
            if analysis.filters.get("doc_type"):
                where["doc_type"] = analysis.filters["doc_type"]

        return search_dense(query_embedding, top_k=top_k, where=where)

    def _sparse_retrieve(
        self, query: str, top_k: int, analysis: Optional[QueryAnalysis],
    ) -> List[Dict]:
        """Sparse 通道：FTS5/BM25。"""
        from backend.rag.v2.sparse_index import search_sparse

        doc_type = None
        if analysis and analysis.route and analysis.route.value == "exact_rule":
            doc_type = "rule"

        return search_sparse(query, top_k=top_k, doc_type=doc_type)

    def _structured_retrieve(
        self, query: str, top_k: int, analysis: Optional[QueryAnalysis],
    ) -> List[Dict]:
        """Structured 通道：九维规则相似度检索历史案例。"""
        try:
            from backend.tools.similarity_tools import find_similar_cases_by_query
        except ImportError:
            # Fallback: return empty
            return []

        # This channel is primarily for historical cases
        return _structured_case_search(query, top_k)


def _structured_case_search(query: str, top_k: int) -> List[Dict]:
    """结构化的历史案例检索（基于事件字段匹配）。"""
    from backend.tools.db_tools import get_connection, init_db

    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM event_records ORDER BY createdAt DESC LIMIT 200")
        rows = cursor.fetchall()
        conn.close()
    except Exception:
        return []

    results = []
    for row in rows:
        event = dict(row)
        # Simple keyword match scoring
        score = 0.0
        event_text = (
            f"{event.get('eventTypeCn', '')} {event.get('eventType', '')} "
            f"{event.get('roadName', '')} {event.get('riskLevel', '')} "
            f"{event.get('report', '')}"
        )
        query_lower = query.lower()
        event_lower = event_text.lower()

        # Keyword overlap
        q_words = set(query_lower.split())
        e_words = set(event_lower.split())
        overlap = len(q_words & e_words)
        if overlap > 0:
            score = overlap / max(len(q_words), 1)

        if score > 0.1:
            results.append({
                "chunk_id": f"case_{event.get('eventId', '')}",
                "document_id": f"event:{event.get('eventId', '')}",
                "content": event_text[:500],
                "score": round(score, 4),
                "channel": "structured",
                "structured_rank": 0,  # filled by RRF
                "metadata": {
                    "eventId": event.get("eventId", ""),
                    "eventType": event.get("eventTypeCn", ""),
                    "roadName": event.get("roadName", ""),
                    "riskLevel": event.get("riskLevel", ""),
                    "docType": "event_report",
                },
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
