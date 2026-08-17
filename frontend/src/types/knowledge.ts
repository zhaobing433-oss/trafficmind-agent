/** Knowledge V1 — Phase 16 Round 2 types */

export type DocType = 'rule' | 'dispatch_experience' | 'event_report' | 'daily_report' | 'weekly_report' | 'case' | 'regulation' | 'agent_output' | 'other';
export type DocStatus = 'active' | 'processing' | 'deleted' | 'failed' | 'superseded' | 'expired' | 'draft';
export type AuthorityLevel = 'official' | 'professional' | 'operational' | 'agent_generated' | 'unknown';

export interface KnowledgeDocument {
  documentId: string;
  name: string;
  sourceId: string;
  docType: DocType;
  authorityLevel: AuthorityLevel;
  status: DocStatus;
  contentHash: string;
  version: number;
  chunkCount: number;
  createdAt: string | null;
  updatedAt: string | null;
  sourceUri: string | null;
  eventType: string | null;
  roadName: string | null;
  errorMessage?: string | null;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  content: string;
  effectiveFrom: string | null;
  effectiveTo: string | null;
  jurisdiction: string | null;
  riskLevel: string | null;
}

export interface KnowledgeChunk {
  chunkId: string;
  documentId: string;
  chunkIndex: number;
  sectionPath: string;
  content: string;
  contentHash: string;
  docType: DocType;
  authorityLevel: AuthorityLevel;
  createdAt: string | null;
}

export interface KnowledgeListResponse {
  total: number;
  limit: number;
  offset: number;
  documents: KnowledgeDocument[];
}

export interface KnowledgeChunkListResponse {
  total: number;
  limit: number;
  offset: number;
  chunks: KnowledgeChunk[];
}

export interface KnowledgeDetailResponse {
  document: KnowledgeDocumentDetail;
  chunkCount: number;
}

export interface KnowledgeIndexStatus {
  activeIndexVersion: string | null;
  collectionName: string | null;
  embeddingModel: string | null;
  embeddingDimension: number | null;
  documentCount: number;
  chunkCount: number;
  vectorCount: number | null;
  status: string;
  lastIndexedAt: string | null;
  healthy: boolean;
}

export interface KnowledgeConsistency {
  healthy: boolean;
  issues: string[];
  details: Record<string, unknown>;
}

export interface CreateKnowledgeRequest {
  name: string;
  docType: string;
  content: string;
  metadata?: Record<string, unknown>;
}

/** RAG evidence item from V2 pipeline */
export interface RagEvidenceItem {
  evidenceId?: string;
  documentId?: string;
  chunkId?: string;
  title?: string;
  docType?: string;
  authorityLevel?: string;
  score?: number;
  sectionPath?: string;
  snippet?: string;
  content?: string;
}

export interface RagAnswerResult {
  answer: string;
  grounded: boolean;
  confidence: number;
  retrievalMode: string;
  evidence: RagEvidenceItem[];
  refusalReason?: string | null;
  traceId?: string;
  abstained?: boolean;
}

export const DOC_TYPE_LABELS: Record<string, string> = {
  rule: '规则', dispatch_experience: '调度经验', event_report: '事件报告',
  daily_report: '日报', weekly_report: '周报', case: '案例',
  regulation: '法规', agent_output: 'Agent输出', other: '其他',
};

export const DOC_STATUS_LABELS: Record<string, string> = {
  active: '活跃', processing: '索引中', deleted: '已删除', failed: '索引失败',
  superseded: '已取代', expired: '已过期', draft: '草稿',
};

export const DOC_STATUS_COLORS: Record<string, string> = {
  active: '#52c41a', processing: '#1890ff', deleted: '#8c8c8c', failed: '#ff4d4f',
  superseded: '#faad14', expired: '#d9d9d9', draft: '#1890ff',
};
