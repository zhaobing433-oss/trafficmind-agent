"""
RAG V2 Sparse Index — SQLite FTS5 + Jieba 中文分词 BM25.

Supports exact term matching: "122", "120", "信号配时", "绿信比", "学校门口", "机场高速".
FTS5 unavailable → pure Python BM25 fallback.
"""
from __future__ import annotations
import logging
import math
import os
import re
import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from backend.rag.v2.config import RAG_V2_FTS_PATH
from backend.rag.v2.models import RagChunk, DocType

logger = logging.getLogger("rag.v2.sparse_index")

# Try Jieba
_JIEBA_AVAILABLE = False
try:
    import jieba
    _JIEBA_AVAILABLE = True
except ImportError:
    pass


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(RAG_V2_FTS_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_fts() -> None:
    """初始化 FTS5 表。"""
    conn = _get_conn()
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(
            chunk_id,
            document_id,
            title,
            section_path,
            contextual_content,
            event_type,
            road_name,
            keywords,
            tokenize='unicode61'
        );
    """)
    conn.commit()
    conn.close()


def segment_chinese(text: str) -> str:
    """中文分词后用空格连接，供 FTS5 索引。"""
    if not text:
        return ""
    if _JIEBA_AVAILABLE:
        tokens = jieba.cut(text.strip())
        return " ".join(tokens)
    else:
        # Fallback: character-level bigrams for CJK
        return _char_bigrams(text)


def _char_bigrams(text: str) -> str:
    """Character bigram fallback for Chinese when Jieba unavailable."""
    result = []
    chars = list(text.strip())
    for i, ch in enumerate(chars):
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            # CJK character: use as-is + bigram with next
            result.append(ch)
            if i + 1 < len(chars) and ('一' <= chars[i+1] <= '鿿' or '㐀' <= chars[i+1] <= '䶿'):
                result.append(ch + chars[i+1])
        elif ch.isalnum():
            result.append(ch)
    return " ".join(result)


def extract_keywords(text: str) -> str:
    """提取文本关键词。"""
    # Extract numbers, terms in quotes, and key traffic terms
    keywords = set()
    # Numbers like 122, 120
    for m in re.finditer(r'\b\d{3,4}\b', text):
        keywords.add(m.group())
    # Quoted terms
    for m in re.finditer(r'[「「]([^」」]+)[」」]', text):
        keywords.add(m.group(1))
    # Traffic-specific terms
    traffic_terms = [
        "信号配时", "绿信比", "相位", "匝道", "主干道", "快速路",
        "早高峰", "晚高峰", "平峰", "拥堵", "事故", "违停",
        "逆行", "行人闯入", "信号灯异常", "车辆滞留", "施工占道",
        "学校门口", "医院", "急救通道", "消防通道", "应急车道",
        "分流", "限流", "诱导", "绕行", "管制", "封闭",
        "122", "120", "119", "110",
    ]
    for term in traffic_terms:
        if term in text:
            keywords.add(term)
    return " ".join(sorted(keywords))


def upsert_chunks_fts(chunks: List[RagChunk]) -> bool:
    """批量 upsert chunks 到 FTS5 索引。"""
    if not chunks:
        return True
    conn = _get_conn()
    try:
        # Delete existing chunks for these documents
        doc_ids = list(set(c.document_id for c in chunks))
        for did in doc_ids:
            conn.execute("DELETE FROM rag_fts WHERE document_id=?", (did,))

        # Insert
        for c in chunks:
            kw = extract_keywords(c.raw_content)
            segmented = segment_chinese(c.contextual_content)
            conn.execute(
                "INSERT INTO rag_fts (chunk_id, document_id, title, section_path, contextual_content, event_type, road_name, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    c.chunk_id, c.document_id,
                    "",
                    c.section_path,
                    segmented,
                    c.event_type or "",
                    c.road_name or "",
                    kw,
                ),
            )
        conn.commit()
        logger.info(f"FTS5 upsert: {len(chunks)} chunks")
        return True
    except Exception as e:
        logger.error(f"FTS5 upsert failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def search_sparse(
    query: str,
    top_k: int = 30,
    doc_type: Optional[str] = None,
    collection_name: str = None,  # ignored, kept for API compatibility
) -> List[Dict]:
    """FTS5 全文检索 + BM25 评分。

    Args:
        query: 查询文本
        top_k: 返回数量
        doc_type: 可选 doc_type 过滤

    Returns:
        [{chunk_id, document_id, content, score, metadata, sparse_rank}, ...]
    """
    # Try FTS5 first
    results = _search_fts5(query, top_k, doc_type)
    if results:
        return results

    # Fallback to pure Python BM25
    logger.warning("FTS5 search returned no results, trying Python BM25 fallback")
    return _search_bm25_python(query, top_k, doc_type)


def _search_fts5(query: str, top_k: int, doc_type: Optional[str]) -> List[Dict]:
    """FTS5 BM25 检索。"""
    conn = _get_conn()
    try:
        segmented = segment_chinese(query)
        if not segmented.strip():
            conn.close()
            return []

        # Use FTS5 BM25() ranking
        where_clause = ""
        params: tuple = (segmented,)
        if doc_type:
            where_clause = " AND c.doc_type = ?"
            params = (segmented, doc_type)

        sql = f"""
            SELECT f.chunk_id, f.document_id, f.section_path, f.contextual_content,
                   f.event_type, f.road_name, f.keywords,
                   bm25(rag_fts, 0.0, 1.0, 0.0, 0.0, 0.75) as bm25_score
            FROM rag_fts f
            JOIN rag_chunks c ON f.chunk_id = c.chunk_id
            JOIN rag_documents d ON c.document_id = d.document_id
            WHERE rag_fts MATCH ? AND d.status = 'active'{where_clause}
            ORDER BY bm25_score
            LIMIT ?
        """
        rows = conn.execute(sql, (*params, top_k)).fetchall()
        conn.close()

        results = []
        for i, row in enumerate(rows):
            r = dict(row)
            score = r.get("bm25_score", 0)
            # Normalize BM25: higher = better (invert negative BM25)
            if score < 0:
                score = 1.0 / (1.0 + abs(score))
            results.append({
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "content": r["contextual_content"],
                "score": round(float(score), 6),
                "sparse_rank": i + 1,
                "channel": "sparse",
                "effective_from": r.get("effective_from") or None,
                "effective_to": r.get("effective_to") or None,
                "status": "active",
                "version": r.get("version", 0),
                "authority_level": r.get("authority_level", "operational"),
                "metadata": {
                    "section_path": r.get("section_path", ""),
                    "event_type": r.get("event_type", ""),
                    "road_name": r.get("road_name", ""),
                    "keywords": r.get("keywords", ""),
                    "effective_from": r.get("effective_from") or None,
                    "effective_to": r.get("effective_to") or None,
                },
            })
        return results
    except Exception as e:
        logger.error(f"FTS5 search failed: {e}")
        conn.close()
        return []


def _search_bm25_python(query: str, top_k: int, doc_type: Optional[str]) -> List[Dict]:
    """Pure Python BM25 fallback — works without FTS5."""
    from backend.rag.v2.document_repository import list_active_chunks

    chunks = list_active_chunks(doc_type)
    if not chunks:
        return []

    # Tokenize
    query_tokens = _tokenize(query)

    # BM25 parameters
    k1 = 1.5
    b = 0.75
    N = len(chunks)
    avgdl = sum(len(_tokenize(c.contextual_content)) for c in chunks) / max(N, 1)

    # Document frequency
    df: Dict[str, int] = defaultdict(int)
    doc_terms: List[Set[str]] = []
    for c in chunks:
        terms = set(_tokenize(c.contextual_content))
        doc_terms.append(terms)
        for t in terms:
            df[t] += 1

    # BM25 score for each document
    scored = []
    for i, c in enumerate(chunks):
        terms = _tokenize(c.contextual_content)
        dl = len(terms)
        score = 0.0
        for qt in query_tokens:
            if qt not in terms:
                continue
            tf = terms.count(qt)
            idf = math.log((N - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1.0)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / avgdl)
            score += idf * numerator / max(denominator, 0.01)

        if score > 0:
            scored.append((i, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:top_k]

    results = []
    for rank, (idx, score) in enumerate(top):
        c = chunks[idx]
        results.append({
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "content": c.contextual_content,
            "score": round(score, 6),
            "sparse_rank": rank + 1,
            "channel": "sparse",
            "effective_from": c.effective_from.isoformat() if c.effective_from else None,
            "effective_to": c.effective_to.isoformat() if c.effective_to else None,
            "status": "active",
            "version": c.version,
            "authority_level": c.authority_level,
            "metadata": {
                "section_path": c.section_path,
                "event_type": c.event_type or "",
                "road_name": c.road_name or "",
                "effective_from": c.effective_from.isoformat() if c.effective_from else None,
                "effective_to": c.effective_to.isoformat() if c.effective_to else None,
            },
        })
    return results


def _tokenize(text: str) -> List[str]:
    """Tokenize text for BM25 (Chinese + English)."""
    if not text:
        return []
    if _JIEBA_AVAILABLE:
        tokens = list(jieba.cut(text))
    else:
        tokens = text.lower().split()
    # Filter short tokens, keep numbers
    return [t.strip() for t in tokens if t.strip() and (len(t.strip()) >= 1)]


# Auto-init
os.makedirs(os.path.dirname(RAG_V2_FTS_PATH), exist_ok=True)
init_fts()
