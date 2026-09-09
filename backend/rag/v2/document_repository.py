"""
RAG V2 Document Repository — SQLite CRUD for RagDocument, RagChunk, index versions, jobs, traces.
"""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.rag.v2.config import RAG_V2_DB_PATH
from backend.rag.v2.models import (
    DocStatus,
    IndexJobResult,
    IndexJobStatus,
    IndexVersion,
    RagChunk,
    RagDocument,
    RagTrace,
    utcnow,
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(RAG_V2_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """初始化 RAG V2 数据库表。"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rag_documents (
            document_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            doc_type TEXT NOT NULL DEFAULT 'other',
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            authority_level TEXT NOT NULL DEFAULT 'operational',
            version INTEGER NOT NULL DEFAULT 1,
            effective_from TEXT,
            effective_to TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            event_type TEXT,
            road_name TEXT,
            risk_level TEXT,
            jurisdiction TEXT,
            region_id TEXT,
            road_id TEXT,
            intersection_id TEXT,
            grounding_scope TEXT NOT NULL DEFAULT 'LEGACY_UNSCOPED',
            source_uri TEXT,
            checksum TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rag_docs_source ON rag_documents(source_id);
        CREATE INDEX IF NOT EXISTS idx_rag_docs_status ON rag_documents(status);
        CREATE INDEX IF NOT EXISTS idx_rag_docs_type ON rag_documents(doc_type);

        CREATE TABLE IF NOT EXISTS rag_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            parent_chunk_id TEXT,
            section_path TEXT NOT NULL DEFAULT '',
            raw_content TEXT NOT NULL DEFAULT '',
            contextual_content TEXT NOT NULL DEFAULT '',
            token_count INTEGER NOT NULL DEFAULT 0,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            doc_type TEXT NOT NULL DEFAULT 'other',
            event_type TEXT,
            road_name TEXT,
            risk_level TEXT,
            authority_level TEXT NOT NULL DEFAULT 'operational',
            version INTEGER NOT NULL DEFAULT 1,
            effective_from TEXT,
            effective_to TEXT,
            region_id TEXT,
            road_id TEXT,
            intersection_id TEXT,
            grounding_scope TEXT NOT NULL DEFAULT 'LEGACY_UNSCOPED',
            checksum TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES rag_documents(document_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_parent ON rag_chunks(parent_chunk_id);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_type ON rag_chunks(doc_type);

        CREATE TABLE IF NOT EXISTS rag_index_versions (
            version_id TEXT PRIMARY KEY,
            collection_name TEXT NOT NULL,
            document_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'building',
            embedding_model TEXT NOT NULL DEFAULT '',
            embedding_dimension INTEGER NOT NULL DEFAULT 0,
            embedding_provider_class TEXT NOT NULL DEFAULT '',
            distance_metric TEXT NOT NULL DEFAULT 'cosine',
            committed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rag_index_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            documents_processed INTEGER NOT NULL DEFAULT 0,
            documents_inserted INTEGER NOT NULL DEFAULT 0,
            documents_updated INTEGER NOT NULL DEFAULT 0,
            documents_skipped INTEGER NOT NULL DEFAULT 0,
            documents_deleted INTEGER NOT NULL DEFAULT 0,
            chunks_upserted INTEGER NOT NULL DEFAULT 0,
            index_version TEXT NOT NULL DEFAULT '',
            errors TEXT NOT NULL DEFAULT '[]',
            duration_ms REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rag_traces (
            trace_id TEXT PRIMARY KEY,
            session_id TEXT,
            event_thread_id TEXT,
            agent_id TEXT,
            original_query TEXT NOT NULL,
            rewritten_query TEXT NOT NULL DEFAULT '',
            subqueries TEXT NOT NULL DEFAULT '[]',
            used_memory_ids TEXT NOT NULL DEFAULT '[]',
            filters TEXT NOT NULL DEFAULT '{}',
            required_facets TEXT NOT NULL DEFAULT '[]',
            stages TEXT NOT NULL DEFAULT '[]',
            candidates_total INTEGER NOT NULL DEFAULT 0,
            accepted_total INTEGER NOT NULL DEFAULT 0,
            rejected_total INTEGER NOT NULL DEFAULT 0,
            evidence_total INTEGER NOT NULL DEFAULT 0,
            evidence_state TEXT NOT NULL DEFAULT 'insufficient',
            index_version TEXT NOT NULL DEFAULT '',
            embedding_model TEXT NOT NULL DEFAULT '',
            reranker_model TEXT NOT NULL DEFAULT '',
            total_latency_ms REAL NOT NULL DEFAULT 0.0,
            degraded INTEGER NOT NULL DEFAULT 0,
            degraded_reasons TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
    """)
    # Migration: add embedding metadata columns to existing tables
    for col_name, col_type in [
        ("embedding_model", "TEXT NOT NULL DEFAULT ''"),
        ("embedding_dimension", "INTEGER NOT NULL DEFAULT 0"),
        ("distance_metric", "TEXT NOT NULL DEFAULT 'cosine'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE rag_index_versions ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists
    for table in ("rag_documents", "rag_chunks"):
        for col_name, col_type in [
            ("region_id", "TEXT"),
            ("road_id", "TEXT"),
            ("intersection_id", "TEXT"),
            ("grounding_scope", "TEXT NOT NULL DEFAULT 'LEGACY_UNSCOPED'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_docs_region ON rag_documents(region_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_region ON rag_chunks(region_id)")
    conn.commit()
    conn.close()


# ─── Document CRUD ───────────────────────────────────────────────────────────

def upsert_document(doc: RagDocument) -> str:
    """插入或更新文档。返回 document_id。"""
    conn = _get_conn()
    try:
        now = utcnow().isoformat()
        conn.execute("""
            INSERT INTO rag_documents (document_id, source_id, doc_type, title, content,
                authority_level, version, effective_from, effective_to, status,
                event_type, road_name, risk_level, jurisdiction,
                region_id, road_id, intersection_id, grounding_scope, source_uri,
                checksum, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                source_id=excluded.source_id,
                doc_type=excluded.doc_type,
                title=excluded.title,
                content=excluded.content,
                authority_level=excluded.authority_level,
                version=excluded.version,
                effective_from=excluded.effective_from,
                effective_to=excluded.effective_to,
                status=excluded.status,
                event_type=excluded.event_type,
                road_name=excluded.road_name,
                risk_level=excluded.risk_level,
                jurisdiction=excluded.jurisdiction,
                region_id=excluded.region_id,
                road_id=excluded.road_id,
                intersection_id=excluded.intersection_id,
                grounding_scope=excluded.grounding_scope,
                source_uri=excluded.source_uri,
                checksum=excluded.checksum,
                updated_at=excluded.updated_at
        """, (
            doc.document_id, doc.source_id, doc.doc_type, doc.title, doc.content,
            doc.authority_level, doc.version,
            doc.effective_from.isoformat() if doc.effective_from else None,
            doc.effective_to.isoformat() if doc.effective_to else None,
            doc.status, doc.event_type, doc.road_name, doc.risk_level,
            doc.jurisdiction, doc.region_id, doc.road_id, doc.intersection_id,
            doc.grounding_scope, doc.source_uri, doc.checksum,
            doc.created_at.isoformat(), now,
        ))
        conn.commit()
        return doc.document_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_document(doc_id: str) -> Optional[RagDocument]:
    """查询单个文档。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM rag_documents WHERE document_id=?", (doc_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_document(dict(row))


def get_document_by_source(source_id: str) -> Optional[RagDocument]:
    """按 source_id 查询文档。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM rag_documents WHERE source_id=? AND status!='deleted' ORDER BY version DESC LIMIT 1",
        (source_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_document(dict(row))


def soft_delete_document(doc_id: str) -> None:
    """软删除文档。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE rag_documents SET status='deleted', updated_at=? WHERE document_id=?",
        (utcnow().isoformat(), doc_id),
    )
    conn.commit()
    conn.close()


def list_active_documents(doc_type: Optional[str] = None) -> List[RagDocument]:
    """列出活跃文档。"""
    conn = _get_conn()
    if doc_type:
        rows = conn.execute(
            "SELECT * FROM rag_documents WHERE status='active' AND doc_type=? ORDER BY updated_at DESC",
            (doc_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rag_documents WHERE status='active' ORDER BY updated_at DESC",
        ).fetchall()
    conn.close()
    return [_row_to_document(dict(r)) for r in rows]


def list_all_documents(doc_type: Optional[str] = None) -> List[RagDocument]:
    """列出所有文档（含 deleted/failed/processing）。"""
    conn = _get_conn()
    if doc_type:
        rows = conn.execute(
            "SELECT * FROM rag_documents WHERE doc_type=? ORDER BY updated_at DESC",
            (doc_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rag_documents ORDER BY updated_at DESC",
        ).fetchall()
    conn.close()
    return [_row_to_document(dict(r)) for r in rows]


def _row_to_document(row: dict) -> RagDocument:
    return RagDocument(
        document_id=row["document_id"],
        source_id=row["source_id"],
        doc_type=row["doc_type"],
        title=row["title"],
        content=row["content"],
        authority_level=row["authority_level"],
        version=row["version"],
        effective_from=_parse_dt(row.get("effective_from")),
        effective_to=_parse_dt(row.get("effective_to")),
        status=row["status"],
        event_type=row.get("event_type"),
        road_name=row.get("road_name"),
        risk_level=row.get("risk_level"),
        jurisdiction=row.get("jurisdiction"),
        region_id=row.get("region_id"),
        road_id=row.get("road_id"),
        intersection_id=row.get("intersection_id"),
        grounding_scope=row.get("grounding_scope") or "LEGACY_UNSCOPED",
        source_uri=row.get("source_uri"),
        checksum=row["checksum"],
        created_at=_parse_dt(row["created_at"]) or utcnow(),
        updated_at=_parse_dt(row["updated_at"]) or utcnow(),
    )


# ─── Chunk CRUD ─────────────────────────────────────────────────────────────

def upsert_chunks(chunks: List[RagChunk]) -> None:
    """批量 upsert chunks。"""
    if not chunks:
        return
    conn = _get_conn()
    now = utcnow().isoformat()
    conn.execute("DELETE FROM rag_chunks WHERE document_id=?", (chunks[0].document_id,))
    for c in chunks:
        conn.execute("""
            INSERT INTO rag_chunks (chunk_id, document_id, parent_chunk_id, section_path,
                raw_content, contextual_content, token_count, chunk_index,
                doc_type, event_type, road_name, risk_level, authority_level,
                version, effective_from, effective_to,
                region_id, road_id, intersection_id, grounding_scope,
                checksum, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c.chunk_id, c.document_id, c.parent_chunk_id, c.section_path,
            c.raw_content, c.contextual_content, c.token_count, c.chunk_index,
            c.doc_type, c.event_type, c.road_name, c.risk_level,
            c.authority_level, c.version,
            c.effective_from.isoformat() if c.effective_from else None,
            c.effective_to.isoformat() if c.effective_to else None,
            c.region_id, c.road_id, c.intersection_id, c.grounding_scope,
            c.checksum, c.created_at.isoformat(), now,
        ))
    conn.commit()
    conn.close()


def get_chunks_by_document(doc_id: str, active_only: bool = True) -> List[RagChunk]:
    """获取文档的所有 chunks。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM rag_chunks WHERE document_id=? ORDER BY chunk_index",
        (doc_id,),
    ).fetchall()
    conn.close()
    return [_row_to_chunk(dict(r)) for r in rows]


def get_chunk(chunk_id: str) -> Optional[RagChunk]:
    """获取单个 chunk。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM rag_chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_chunk(dict(row))


def delete_chunks_by_document(doc_id: str) -> None:
    """删除文档的所有 chunks。"""
    conn = _get_conn()
    conn.execute("DELETE FROM rag_chunks WHERE document_id=?", (doc_id,))
    conn.commit()
    conn.close()


def list_active_chunks(doc_type: Optional[str] = None) -> List[RagChunk]:
    """列出活跃 chunks（关联活跃文档）。"""
    conn = _get_conn()
    if doc_type:
        rows = conn.execute("""
            SELECT c.* FROM rag_chunks c
            JOIN rag_documents d ON c.document_id = d.document_id
            WHERE d.status = 'active' AND c.doc_type = ?
            ORDER BY c.chunk_index
        """, (doc_type,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT c.* FROM rag_chunks c
            JOIN rag_documents d ON c.document_id = d.document_id
            WHERE d.status = 'active'
            ORDER BY c.chunk_index
        """).fetchall()
    conn.close()
    return [_row_to_chunk(dict(r)) for r in rows]


def _row_to_chunk(row: dict) -> RagChunk:
    return RagChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        parent_chunk_id=row.get("parent_chunk_id"),
        section_path=row["section_path"],
        raw_content=row["raw_content"],
        contextual_content=row["contextual_content"],
        token_count=row["token_count"],
        chunk_index=row["chunk_index"],
        doc_type=row["doc_type"],
        event_type=row.get("event_type"),
        road_name=row.get("road_name"),
        risk_level=row.get("risk_level"),
        authority_level=row["authority_level"],
        version=row["version"],
        effective_from=_parse_dt(row.get("effective_from")),
        effective_to=_parse_dt(row.get("effective_to")),
        region_id=row.get("region_id"),
        road_id=row.get("road_id"),
        intersection_id=row.get("intersection_id"),
        grounding_scope=row.get("grounding_scope") or "LEGACY_UNSCOPED",
        checksum=row["checksum"],
        created_at=_parse_dt(row["created_at"]) or utcnow(),
        updated_at=_parse_dt(row["updated_at"]) or utcnow(),
    )


# ─── Index Version CRUD ─────────────────────────────────────────────────────

def create_index_version(
    collection_name: str,
    embedding_model: str = "",
    embedding_dimension: int = 0,
    distance_metric: str = "cosine",
) -> IndexVersion:
    """创建新索引版本。"""
    ver = IndexVersion(
        version_id=f"iv_{uuid.uuid4().hex[:12]}",
        collection_name=collection_name,
        status="building",
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        distance_metric=distance_metric,
    )
    conn = _get_conn()
    conn.execute(
        """INSERT INTO rag_index_versions (version_id, collection_name, document_count, chunk_count,
           status, embedding_model, embedding_dimension, distance_metric, committed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ver.version_id, ver.collection_name, ver.document_count, ver.chunk_count,
         ver.status, ver.embedding_model, ver.embedding_dimension,
         ver.distance_metric,
         ver.committed_at.isoformat()),
    )
    conn.commit()
    conn.close()
    return ver


def commit_index_version(
    version_id: str, doc_count: int, chunk_count: int,
    embedding_model: str = "", embedding_dimension: int = 0,
    distance_metric: str = "cosine",
) -> None:
    """提交索引版本。"""
    conn = _get_conn()
    conn.execute(
        """UPDATE rag_index_versions SET status='active', document_count=?, chunk_count=?,
           embedding_model=?, embedding_dimension=?, distance_metric=?,
           committed_at=? WHERE version_id=?""",
        (doc_count, chunk_count, embedding_model, embedding_dimension,
         distance_metric,
         utcnow().isoformat(), version_id),
    )
    # Mark older versions as superseded
    conn.execute(
        "UPDATE rag_index_versions SET status='superseded' WHERE version_id!=? AND status='active'",
        (version_id,),
    )
    conn.commit()
    conn.close()


def get_latest_index_version() -> Optional[IndexVersion]:
    """获取最新活跃索引版本。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM rag_index_versions WHERE status='active' ORDER BY committed_at DESC LIMIT 1",
    ).fetchone()
    conn.close()
    if row is None:
        return None
    r = dict(row)
    return IndexVersion(
        version_id=r["version_id"],
        collection_name=r["collection_name"],
        document_count=r["document_count"],
        chunk_count=r["chunk_count"],
        status=r["status"],
        embedding_model=r.get("embedding_model", ""),
        embedding_dimension=r.get("embedding_dimension", 0),
        distance_metric=r.get("distance_metric", "cosine"),
        committed_at=_parse_dt(r["committed_at"]) or utcnow(),
    )


def get_active_collection_name() -> str:
    """获取当前活跃的 collection 名称。"""
    from backend.rag.v2.config import RAG_V2_COLLECTION_NAME
    ver = get_latest_index_version()
    if ver and ver.collection_name:
        return ver.collection_name
    return RAG_V2_COLLECTION_NAME


def get_latest_version_for_collection(collection_name: str) -> Optional[IndexVersion]:
    """获取指定 collection 的最新版本记录。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM rag_index_versions WHERE collection_name=? ORDER BY committed_at DESC LIMIT 1",
        (collection_name,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    r = dict(row)
    return IndexVersion(
        version_id=r["version_id"],
        collection_name=r["collection_name"],
        document_count=r["document_count"],
        chunk_count=r["chunk_count"],
        status=r["status"],
        embedding_model=r.get("embedding_model", ""),
        embedding_dimension=r.get("embedding_dimension", 0),
        distance_metric=r.get("distance_metric", "cosine"),
        committed_at=_parse_dt(r["committed_at"]) or utcnow(),
    )


# ─── Index Job CRUD ─────────────────────────────────────────────────────────

def create_index_job() -> IndexJobResult:
    """创建索引作业。"""
    job = IndexJobResult(job_id=f"job_{uuid.uuid4().hex[:12]}")
    conn = _get_conn()
    conn.execute(
        "INSERT INTO rag_index_jobs (job_id, status, created_at) VALUES (?, ?, ?)",
        (job.job_id, job.status, job.created_at.isoformat()),
    )
    conn.commit()
    conn.close()
    return job


def update_index_job(job: IndexJobResult) -> None:
    """更新索引作业。"""
    conn = _get_conn()
    conn.execute(
        """UPDATE rag_index_jobs SET status=?, documents_processed=?, documents_inserted=?,
           documents_updated=?, documents_skipped=?, documents_deleted=?,
           chunks_upserted=?, index_version=?, errors=?, duration_ms=? WHERE job_id=?""",
        (
            job.status, job.documents_processed, job.documents_inserted,
            job.documents_updated, job.documents_skipped, job.documents_deleted,
            job.chunks_upserted, job.index_version,
            json.dumps(job.errors, ensure_ascii=False),
            job.duration_ms, job.job_id,
        ),
    )
    conn.commit()
    conn.close()


# ─── Trace CRUD ─────────────────────────────────────────────────────────────

def save_trace(trace: RagTrace) -> None:
    """保存 RAG Trace。"""
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO rag_traces (trace_id, session_id, event_thread_id, agent_id,
           original_query, rewritten_query, subqueries, used_memory_ids, filters,
           required_facets, stages, candidates_total, accepted_total, rejected_total,
           evidence_total, evidence_state, index_version, embedding_model, reranker_model,
           total_latency_ms, degraded, degraded_reasons, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trace.trace_id, trace.session_id, trace.event_thread_id, trace.agent_id,
            trace.original_query, trace.rewritten_query,
            json.dumps(trace.subqueries, ensure_ascii=False),
            json.dumps(trace.used_memory_ids, ensure_ascii=False),
            json.dumps(trace.filters, ensure_ascii=False),
            json.dumps(trace.required_facets, ensure_ascii=False),
            json.dumps([s.model_dump(mode="json") for s in trace.stages], ensure_ascii=False, default=str),
            trace.candidates_total, trace.accepted_total, trace.rejected_total,
            trace.evidence_total, trace.evidence_state,
            trace.index_version, trace.embedding_model, trace.reranker_model,
            trace.total_latency_ms, int(trace.degraded),
            json.dumps(trace.degraded_reasons, ensure_ascii=False),
            trace.created_at.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_trace(trace_id: str) -> Optional[RagTrace]:
    """查询 RAG Trace。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM rag_traces WHERE trace_id=?", (trace_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    r = dict(row)
    return RagTrace(
        trace_id=r["trace_id"],
        session_id=r.get("session_id"),
        event_thread_id=r.get("event_thread_id"),
        agent_id=r.get("agent_id"),
        original_query=r["original_query"],
        rewritten_query=r.get("rewritten_query", ""),
        subqueries=json.loads(r.get("subqueries", "[]")),
        used_memory_ids=json.loads(r.get("used_memory_ids", "[]")),
        filters=json.loads(r.get("filters", "{}")),
        required_facets=json.loads(r.get("required_facets", "[]")),
        stages=json.loads(r.get("stages", "[]")),
        candidates_total=r.get("candidates_total", 0),
        accepted_total=r.get("accepted_total", 0),
        rejected_total=r.get("rejected_total", 0),
        evidence_total=r.get("evidence_total", 0),
        evidence_state=r.get("evidence_state", "insufficient"),
        index_version=r.get("index_version", ""),
        embedding_model=r.get("embedding_model", ""),
        reranker_model=r.get("reranker_model", ""),
        total_latency_ms=r.get("total_latency_ms", 0.0),
        degraded=bool(r.get("degraded", False)),
        degraded_reasons=json.loads(r.get("degraded_reasons", "[]")),
        created_at=_parse_dt(r["created_at"]) or utcnow(),
    )


def delete_traces_by_session(session_id: str) -> int:
    """删除会话关联的所有 Traces。"""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM rag_traces WHERE session_id=?", (session_id,))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        s = str(val).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# Auto-initialize on import
os.makedirs(os.path.dirname(RAG_V2_DB_PATH), exist_ok=True)
init_db()
