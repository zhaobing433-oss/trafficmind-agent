/**
 * RAG V2 前端类型定义 — Phase 11
 *
 * snake_case → camelCase 转换统一在 API 层完成。
 * 组件内部只使用 camelCase。
 */

// ================================================================
// Enums
// ================================================================

export type RetrievalRoute =
  | "no_retrieval"
  | "exact_rule"
  | "operational_guidance"
  | "similar_case"
  | "cross_document"
  | "multi_hop";

export type EvidenceState =
  | "sufficient"
  | "partial"
  | "insufficient"
  | "contradictory";

export type DocType =
  | "rule"
  | "dispatch_experience"
  | "event_report"
  | "daily_report"
  | "weekly_report"
  | "case"
  | "regulation"
  | "agent_output"
  | "other";

export type AuthorityLevel =
  | "official"
  | "professional"
  | "operational"
  | "agent_generated"
  | "unknown";

export type TraceStageName =
  | "query_analysis"
  | "query_rewrite"
  | "query_decomposition"
  | "hybrid_retrieval"
  | "rerank_and_policy"
  | "evidence_evaluation"
  | "generation";

// ================================================================
// Labels
// ================================================================

export const ROUTE_LABELS: Record<RetrievalRoute, string> = {
  no_retrieval: "无需检索",
  exact_rule: "精确规则",
  operational_guidance: "处置指引",
  similar_case: "相似案例",
  cross_document: "跨文档",
  multi_hop: "多跳推理",
};

export const EVIDENCE_STATE_LABELS: Record<EvidenceState, string> = {
  sufficient: "充分",
  partial: "部分",
  insufficient: "不足",
  contradictory: "冲突",
};

export const EVIDENCE_STATE_COLORS: Record<EvidenceState, string> = {
  sufficient: "green",
  partial: "orange",
  insufficient: "red",
  contradictory: "volcano",
};

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  rule: "处置预案",
  dispatch_experience: "调度经验",
  event_report: "事件报告",
  daily_report: "日报",
  weekly_report: "周报",
  case: "案例",
  regulation: "法规",
  agent_output: "Agent产出",
  other: "其他",
};

export const AUTHORITY_LABELS: Record<AuthorityLevel, string> = {
  official: "正式法规",
  professional: "专业指南",
  operational: "运营经验",
  agent_generated: "Agent生成",
  unknown: "未知",
};

// ================================================================
// Core Models
// ================================================================

export interface RagEvidenceItem {
  evidenceId: string;
  chunkId: string;
  documentId: string;
  parentChunkId?: string;
  title: string;
  sectionPath: string;
  docType: DocType;
  content: string;
  contextualContent: string;
  authorityLevel: AuthorityLevel;
  effectiveFrom?: string;
  effectiveTo?: string;
  retrievalChannels: string[];
  rrfScore?: number;
  rerankScore?: number;
  sourceUri?: string;
}

export interface RagCitationMap {
  citationId: string;
  evidenceId: string;
  textSpan: string;
}

export interface RagTraceStage {
  stage: string;
  startTs: string;
  endTs?: string;
  durationMs: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  degraded: boolean;
  error?: string;
}

export interface RagTrace {
  traceId: string;
  sessionId?: string;
  eventThreadId?: string;
  agentId?: string;
  originalQuery: string;
  rewrittenQuery: string;
  subqueries: string[];
  usedMemoryIds: string[];
  filters: Record<string, unknown>;
  requiredFacets: string[];
  stages: RagTraceStage[];
  candidatesTotal: number;
  acceptedTotal: number;
  rejectedTotal: number;
  evidenceTotal: number;
  evidenceState: EvidenceState;
  indexVersion: string;
  embeddingModel: string;
  rerankerModel: string;
  totalLatencyMs: number;
  degraded: boolean;
  degradedReasons: string[];
  createdAt: string;
}

export interface RagSearchResult {
  chunkId: string;
  documentId: string;
  content: string;
  score: number;
  denseRank?: number;
  sparseRank?: number;
  structuredRank?: number;
  rrfScore?: number;
  rerankScore?: number;
  retrievalChannels: string[];
  metadata: Record<string, unknown>;
}

export interface RagAnswer {
  question: string;
  answer: string;
  evidence: RagEvidenceItem[];
  citationMap: RagCitationMap[];
  confidence: number;
  evidenceState: EvidenceState;
  abstained: boolean;
  abstainReason: string;
  traceId: string;
  usedMemory: string[];
  usedLlm: boolean;
  degradedMode: boolean;
  degradedReasons: string[];
  indexVersion: string;
  embeddingModel: string;
  rerankerModel: string;
  latencyMs: Record<string, number>;
}

export interface RagV2Status {
  ragV2Enabled: boolean;
  indexVersion?: {
    versionId: string;
    collectionName: string;
    documentCount: number;
    chunkCount: number;
    status: string;
    committedAt: string;
  };
  embeddingModel: string;
  embeddingDegraded: boolean;
  rerankerModel: string;
  rerankerDegraded: boolean;
  chunksInChroma: number;
}

// ================================================================
// Empty defaults
// ================================================================

export const EMPTY_RAG_TRACE: RagTrace = {
  traceId: "",
  originalQuery: "",
  rewrittenQuery: "",
  subqueries: [],
  usedMemoryIds: [],
  filters: {},
  requiredFacets: [],
  stages: [],
  candidatesTotal: 0,
  acceptedTotal: 0,
  rejectedTotal: 0,
  evidenceTotal: 0,
  evidenceState: "insufficient",
  indexVersion: "",
  embeddingModel: "",
  rerankerModel: "",
  totalLatencyMs: 0,
  degraded: false,
  degradedReasons: [],
  createdAt: "",
};

export const EMPTY_RAG_ANSWER: RagAnswer = {
  question: "",
  answer: "",
  evidence: [],
  citationMap: [],
  confidence: 0,
  evidenceState: "insufficient",
  abstained: false,
  abstainReason: "",
  traceId: "",
  usedMemory: [],
  usedLlm: false,
  degradedMode: false,
  degradedReasons: [],
  indexVersion: "",
  embeddingModel: "",
  rerankerModel: "",
  latencyMs: {},
};
