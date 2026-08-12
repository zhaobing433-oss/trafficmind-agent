"""
RAG V2 核心数据模型 — Pydantic v2
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Enums ───────────────────────────────────────────────────────────────────

class DocType(str, Enum):
    RULE = "rule"
    DISPATCH_EXPERIENCE = "dispatch_experience"
    EVENT_REPORT = "event_report"
    DAILY_REPORT = "daily_report"
    WEEKLY_REPORT = "weekly_report"
    CASE = "case"
    REGULATION = "regulation"
    AGENT_OUTPUT = "agent_output"
    OTHER = "other"


class DocStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DRAFT = "draft"
    DELETED = "deleted"


class AuthorityLevel(str, Enum):
    OFFICIAL = "official"           # 正式法规/国标
    PROFESSIONAL = "professional"   # 专业机构指南
    OPERATIONAL = "operational"     # 运营经验沉淀
    AGENT_GENERATED = "agent_generated"  # Agent 产出
    UNKNOWN = "unknown"


class EvidenceState(str, Enum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    CONTRADICTORY = "contradictory"


class RetrievalRoute(str, Enum):
    NO_RETRIEVAL = "no_retrieval"
    EXACT_RULE = "exact_rule"
    OPERATIONAL_GUIDANCE = "operational_guidance"
    SIMILAR_CASE = "similar_case"
    CROSS_DOCUMENT = "cross_document"
    MULTI_HOP = "multi_hop"


class IndexJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# ─── Document models ─────────────────────────────────────────────────────────

class RagDocument(BaseModel):
    """知识文档元数据。"""
    document_id: str
    source_id: str                           # 来源唯一标识（规则路径/事件ID等）
    doc_type: DocType = DocType.OTHER
    title: str
    content: str = ""
    authority_level: AuthorityLevel = AuthorityLevel.OPERATIONAL
    version: int = 1
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    status: DocStatus = DocStatus.ACTIVE
    event_type: Optional[str] = None         # 拥堵/事故/违停...
    road_name: Optional[str] = None
    risk_level: Optional[str] = None         # 低/中/高/重大
    jurisdiction: Optional[str] = None       # 管辖区域
    source_uri: Optional[str] = None
    checksum: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = ConfigDict(use_enum_values=True)


class RagChunk(BaseModel):
    """知识分块 — Parent-Child 结构。"""
    chunk_id: str
    document_id: str
    parent_chunk_id: Optional[str] = None    # 所属 parent chunk
    section_path: str = ""                   # e.g. "四、拥堵处置 > 早高峰 > 市区主路"
    raw_content: str = ""                    # 原始文本
    contextual_content: str = ""             # 带 Context Prefix 的文本（用于检索）
    token_count: int = 0
    chunk_index: int = 0                     # 在文档中的序号
    doc_type: DocType = DocType.OTHER
    event_type: Optional[str] = None
    road_name: Optional[str] = None
    risk_level: Optional[str] = None
    authority_level: AuthorityLevel = AuthorityLevel.OPERATIONAL
    version: int = 1
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    checksum: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    model_config = ConfigDict(use_enum_values=True)


# ─── Query models ────────────────────────────────────────────────────────────

class QueryAnalysis(BaseModel):
    """查询分析结果。"""
    needs_retrieval: bool = True
    complexity: str = "simple"                # simple / moderate / complex
    route: RetrievalRoute = RetrievalRoute.CROSS_DOCUMENT
    explicit_entities: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    required_facets: List[str] = Field(default_factory=list)
    subqueries: List[str] = Field(default_factory=list)
    reason: str = ""


class RetrievalRequest(BaseModel):
    """检索请求。"""
    original_query: str
    rewritten_query: str = ""
    subqueries: List[str] = Field(default_factory=list)
    analysis: Optional[QueryAnalysis] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    event_thread_id: Optional[str] = None
    agent_id: Optional[str] = None
    used_memory_ids: List[str] = Field(default_factory=list)


class RetrievalCandidate(BaseModel):
    """检索候选。"""
    chunk_id: str
    document_id: str
    parent_chunk_id: Optional[str] = None
    content: str
    contextual_content: str = ""
    section_path: str = ""
    doc_type: DocType = DocType.OTHER
    title: str = ""
    authority_level: AuthorityLevel = AuthorityLevel.OPERATIONAL
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    source_uri: Optional[str] = None
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    structured_rank: Optional[int] = None
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None
    structured_score: Optional[float] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None
    rerank_rank: Optional[int] = None
    retrieval_channels: List[str] = Field(default_factory=list)
    accepted: bool = False
    rejection_reason: str = ""


class EvidenceItem(BaseModel):
    """最终采纳的证据。"""
    evidence_id: str                        # E1, E2, E3...
    chunk_id: str
    document_id: str
    parent_chunk_id: Optional[str] = None
    title: str
    section_path: str = ""
    doc_type: DocType = DocType.OTHER
    content: str
    contextual_content: str = ""
    authority_level: AuthorityLevel = AuthorityLevel.OPERATIONAL
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    retrieval_channels: List[str] = Field(default_factory=list)
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None
    source_uri: Optional[str] = None


# ─── Answer model ────────────────────────────────────────────────────────────

class CitationMap(BaseModel):
    """引用映射。"""
    citation_id: str                        # e.g. "E1"
    evidence_id: str
    text_span: str = ""                     # 回答中被引用的文本片段


class RagAnswer(BaseModel):
    """RAG 回答。"""
    question: str
    answer: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    citation_map: List[CitationMap] = Field(default_factory=list)
    confidence: float = 0.0
    evidence_state: EvidenceState = EvidenceState.INSUFFICIENT
    abstained: bool = False
    abstain_reason: str = ""
    trace_id: str = ""
    used_memory: List[str] = Field(default_factory=list)
    used_llm: bool = False
    degraded_mode: bool = False
    degraded_reasons: List[str] = Field(default_factory=list)
    index_version: str = ""
    embedding_model: str = ""
    reranker_model: str = ""
    latency_ms: Dict[str, float] = Field(default_factory=dict)


# ─── Trace models ────────────────────────────────────────────────────────────

class TraceStage(BaseModel):
    """Trace 单个阶段记录。"""
    stage: str
    start_ts: datetime = Field(default_factory=utcnow)
    end_ts: Optional[datetime] = None
    duration_ms: float = 0.0
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
    error: Optional[str] = None


class RagTrace(BaseModel):
    """完整 RAG 追踪。"""
    trace_id: str
    session_id: Optional[str] = None
    event_thread_id: Optional[str] = None
    agent_id: Optional[str] = None
    original_query: str
    rewritten_query: str = ""
    subqueries: List[str] = Field(default_factory=list)
    used_memory_ids: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    required_facets: List[str] = Field(default_factory=list)
    stages: List[TraceStage] = Field(default_factory=list)
    candidates_total: int = 0
    accepted_total: int = 0
    rejected_total: int = 0
    evidence_total: int = 0
    evidence_state: EvidenceState = EvidenceState.INSUFFICIENT
    index_version: str = ""
    embedding_model: str = ""
    reranker_model: str = ""
    total_latency_ms: float = 0.0
    degraded: bool = False
    degraded_reasons: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


# ─── Index models ────────────────────────────────────────────────────────────

class IndexJobResult(BaseModel):
    """索引作业结果。"""
    job_id: str
    status: IndexJobStatus = IndexJobStatus.PENDING
    documents_processed: int = 0
    documents_inserted: int = 0
    documents_updated: int = 0
    documents_skipped: int = 0
    documents_deleted: int = 0
    chunks_upserted: int = 0
    index_version: str = ""
    errors: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)


class IndexVersion(BaseModel):
    """索引版本记录。"""
    version_id: str
    collection_name: str
    document_count: int = 0
    chunk_count: int = 0
    status: str = "active"                  # active / building / failed / superseded
    embedding_model: str = ""
    embedding_dimension: int = 0
    distance_metric: str = "cosine"
    committed_at: datetime = Field(default_factory=utcnow)
