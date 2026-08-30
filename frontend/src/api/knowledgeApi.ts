/** Knowledge API client — Phase 16 Round 2 */
import type {
  KnowledgeListResponse, KnowledgeDetailResponse, KnowledgeChunkListResponse,
  KnowledgeIndexStatus, KnowledgeConsistency, KnowledgeDocument, CreateKnowledgeRequest,
} from '../types/knowledge';

const API = '/api';

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error((e as { detail?: string }).detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export function listDocuments(params?: {
  status?: string; doc_type?: string; limit?: number; offset?: number; include_deleted?: boolean;
}): Promise<KnowledgeListResponse> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set('status', params.status);
  if (params?.doc_type) qs.set('doc_type', params.doc_type);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.include_deleted) qs.set('include_deleted', 'true');
  const q = qs.toString();
  return getJson(`${API}/knowledge/documents${q ? '?' + q : ''}`);
}

export function getDocument(id: string): Promise<KnowledgeDetailResponse> {
  return getJson(`${API}/knowledge/documents/${encodeURIComponent(id)}`);
}

export function getChunks(id: string, limit = 50, offset = 0): Promise<KnowledgeChunkListResponse> {
  return getJson(`${API}/knowledge/documents/${encodeURIComponent(id)}/chunks?limit=${limit}&offset=${offset}`);
}

export function createDocument(body: CreateKnowledgeRequest): Promise<KnowledgeDocument> {
  return fetch(`${API}/knowledge/documents`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then(r => r.ok ? r.json() : r.json().then(e => { throw new Error((e as { detail?: string }).detail || `HTTP ${r.status}`); }));
}

/** 上传 TXT/MD 文件录入知识文档（多部分表单，与文本录入共用同一摄取管道） */
export function uploadDocument(file: File, docType: string): Promise<KnowledgeDocument> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('doc_type', docType);
  return fetch(`${API}/knowledge/documents/upload`, { method: 'POST', body: fd })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error((e as { detail?: string }).detail || `HTTP ${r.status}`); }));
}

export function deleteDocument(id: string): Promise<{ documentId: string; status: string }> {
  return fetch(`${API}/knowledge/documents/${encodeURIComponent(id)}`, { method: 'DELETE' })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error((e as { detail?: string }).detail || `HTTP ${r.status}`); }));
}

export function reindexDocument(id: string): Promise<KnowledgeDocument> {
  return fetch(`${API}/knowledge/documents/${encodeURIComponent(id)}/reindex`, { method: 'POST' })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error((e as { detail?: string }).detail || `HTTP ${r.status}`); }));
}

export function getIndexStatus(): Promise<KnowledgeIndexStatus> {
  return getJson(`${API}/knowledge/index/status`);
}

export function getConsistency(): Promise<KnowledgeConsistency> {
  return getJson(`${API}/knowledge/index/consistency`);
}
