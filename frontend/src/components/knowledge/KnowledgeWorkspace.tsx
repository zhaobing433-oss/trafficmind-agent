/**
 * KnowledgeWorkspace — Phase 16 Round 2
 * Tab: [知识文档] [知识问答]
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import ChatWorkspace from '../ChatWorkspace';
import {
  listDocuments, getDocument, getChunks, createDocument, deleteDocument, reindexDocument, getIndexStatus, getConsistency,
} from '../../api/knowledgeApi';
import type { KnowledgeDocument, KnowledgeDocumentDetail, KnowledgeChunk, KnowledgeIndexStatus, KnowledgeConsistency } from '../../types/knowledge';
import { DOC_TYPE_LABELS, DOC_STATUS_LABELS, DOC_STATUS_COLORS } from '../../types/knowledge';
import { formatDateTime } from '../../utils/format';

type Tab = 'documents' | 'ask';

interface Props {
  onRefresh: () => void;
  activeSessionId?: string;
}

const PAGE_SIZE = 20;

export const KnowledgeWorkspace: React.FC<Props> = ({ onRefresh, activeSessionId }) => {
  const [tab, setTab] = useState<Tab>(() => {
    const p = new URLSearchParams(window.location.search);
    // Evidence deep-link: show documents tab if navigating from evidence
    if (p.get('knowledgeDocumentId')) return 'documents';
    if (p.get('knowledgeTab') === 'ask') return 'ask';
    // RAG conversation restore: a sessionId implies the ask tab
    if (p.get('sessionId')) return 'ask';
    return 'documents';
  });

  // Evidence deep-link support
  const [highlightChunkId, setHighlightChunkId] = useState<string | null>(() => {
    const p = new URLSearchParams(window.location.search);
    return p.get('knowledgeChunkId') || null;
  });

  const setTabAndUrl = useCallback((t: Tab) => {
    setTab(t);
    const url = new URL(window.location.href);
    if (t === 'ask') url.searchParams.set('knowledgeTab', 'ask');
    else url.searchParams.delete('knowledgeTab');
    window.history.replaceState({}, '', url.toString());
  }, []);

  // Document list state
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [totalDocs, setTotalDocs] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Index health
  const [health, setHealth] = useState<KnowledgeIndexStatus | null>(null);
  const [consistency, setConsistency] = useState<KnowledgeConsistency | null>(null);

  // Detail modal
  const [detailDoc, setDetailDoc] = useState<KnowledgeDocumentDetail | null>(null);
  const [detailChunks, setDetailChunks] = useState<KnowledgeChunk[]>([]);
  const [detailOpen, setDetailOpen] = useState(false);

  // Ingest modal
  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestName, setIngestName] = useState('');
  const [ingestType, setIngestType] = useState('rule');
  const [ingestContent, setIngestContent] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<string | null>(null);

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Quick questions
  const quickQs = ['雨天早高峰拥堵有哪些处置原则？', '信号灯异常应该优先检索哪些预案？', '学校周边拥堵需要关注哪些安全因素？', '为什么证据不足时系统会拒答？', '高风险路口如何判定？'];
  const [askInput, setAskInput] = useState('');

  const loadDocs = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await listDocuments({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
      setDocs(data.documents); setTotalDocs(data.total);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '加载失败'); }
    finally { setLoading(false); }
  }, [page]);

  const loadHealth = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([getIndexStatus(), getConsistency()]);
      setHealth(s); setConsistency(c);
    } catch { /* non-critical */ }
  }, []);

  useEffect(() => { loadDocs(); loadHealth(); }, [loadDocs, loadHealth]);

  // Auto-open document detail from URL deep-link
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const docId = p.get('knowledgeDocumentId');
    if (docId) {
      setTab('documents');
      openDetail(docId);
      setHighlightChunkId(p.get('knowledgeChunkId'));
      // Clean URL after opening
      const url = new URL(window.location.href);
      url.searchParams.delete('knowledgeDocumentId');
      url.searchParams.delete('knowledgeChunkId');
      window.history.replaceState({}, '', url.toString());
    }
  }, []);

  // Detail
  const openDetail = useCallback(async (id: string) => {
    try {
      const [d, c] = await Promise.all([getDocument(id), getChunks(id, 100, 0)]);
      setDetailDoc(d.document); setDetailChunks(c.chunks); setDetailOpen(true);
    } catch { /* ignore */ }
  }, []);

  // Ingest
  const handleIngest = useCallback(async () => {
    if (!ingestName.trim() || !ingestContent.trim()) return;
    setIngesting(true); setIngestError(null);
    try {
      await createDocument({ name: ingestName.trim(), docType: ingestType, content: ingestContent });
      setIngestOpen(false); setIngestName(''); setIngestContent('');
      loadDocs(); loadHealth();
    } catch (e: unknown) { setIngestError(e instanceof Error ? e.message : '创建失败'); }
    finally { setIngesting(false); }
  }, [ingestName, ingestType, ingestContent, loadDocs, loadHealth]);

  // Delete
  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try { await deleteDocument(deleteTarget); setDeleteTarget(null); loadDocs(); loadHealth(); }
    catch (e: unknown) { alert(e instanceof Error ? e.message : '删除失败'); }
    finally { setDeleting(false); }
  }, [deleteTarget, loadDocs, loadHealth]);

  // Reindex
  const handleReindex = useCallback(async (id: string) => {
    try { await reindexDocument(id); loadDocs(); loadHealth(); }
    catch (e: unknown) { alert(e instanceof Error ? e.message : '重新索引失败'); }
  }, [loadDocs, loadHealth]);

  // Quick question
  const handleQuickQ = useCallback((q: string) => {
    setAskInput(q);
    setTabAndUrl('ask');
  }, [setTabAndUrl]);

  const totalPages = Math.max(1, Math.ceil(totalDocs / PAGE_SIZE));

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>知识库</h2>
      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 12px' }}>交通知识文档管理 · RAG检索增强 · 证据问答</p>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '2px solid #E5E7EB' }}>
        {(['documents', 'ask'] as Tab[]).map(t => (
          <button key={t} onClick={() => setTabAndUrl(t)}
            style={{ padding: '8px 20px', fontSize: 13, fontWeight: tab === t ? 600 : 400,
              color: tab === t ? '#0F766E' : '#6B7280', background: 'none', border: 'none',
              borderBottom: tab === t ? '2px solid #0F766E' : '2px solid transparent',
              marginBottom: -2, cursor: 'pointer' }}>
            {t === 'documents' ? '知识文档' : '知识问答'}
          </button>
        ))}
      </div>

      {/* ── Documents Tab ── */}
      {tab === 'documents' && (
        <div>
          {/* Index Health */}
          {health && (
            <div style={{ padding: '8px 14px', borderRadius: 8, marginBottom: 12, fontSize: 12,
              background: health.healthy ? '#F0FDF4' : '#FFF7ED', border: `1px solid ${health.healthy ? '#BBF7D0' : '#FED7AA'}`,
              color: health.healthy ? '#166534' : '#9A3412', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <span>{health.healthy ? '✅ 索引正常' : '⚠ 索引异常'} ·
                模型 {health.embeddingModel || '?'} · {health.embeddingDimension}d ·
                文档 {health.documentCount} · chunks {health.chunkCount} · vectors {health.vectorCount ?? '?'}
                {health.lastIndexedAt && ` · 更新于 ${formatDateTime(health.lastIndexedAt)}`}
              </span>
              {consistency && !consistency.healthy && (
                <span style={{ fontSize: 11, cursor: 'pointer' }} title={consistency.issues.join('\n')}>
                  {consistency.issues.length} 个问题
                </span>
              )}
            </div>
          )}

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button onClick={() => { setIngestOpen(true); setIngestError(null); }}
              style={{ padding: '6px 16px', borderRadius: 6, border: 'none', background: '#0F766E', color: '#FFF', cursor: 'pointer', fontSize: 12 }}>
              + 添加知识
            </button>
            <button onClick={() => { loadDocs(); loadHealth(); }}
              style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12, color: '#6B7280' }}>
              ⟳ 刷新
            </button>
          </div>

          {/* List */}
          {loading ? <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF' }}>加载文档...</div>
          : error ? <div style={{ textAlign: 'center', padding: 40, color: '#DC2626' }}>{error} <button onClick={loadDocs} style={{ cursor: 'pointer', border: '1px solid #E5E7EB', borderRadius: 4, padding: '2px 8px', fontSize: 11 }}>重试</button></div>
          : docs.length === 0 ? <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF' }}>暂无知识文档</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {docs.map(doc => (
                <div key={doc.documentId} style={{ padding: '12px 16px', borderRadius: 8, border: '1px solid #E5E7EB', background: '#FFF', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#111827' }}>
                      <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: DOC_STATUS_COLORS[doc.status] || '#999', marginRight: 6 }} />
                      {doc.name}
                    </div>
                    <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
                      {DOC_TYPE_LABELS[doc.docType] || doc.docType} · v{doc.version} · {doc.chunkCount} chunks
                      {doc.status !== 'active' && <span style={{ marginLeft: 6, color: doc.status === 'failed' ? '#DC2626' : '#9CA3AF' }}>{DOC_STATUS_LABELS[doc.status] || doc.status}</span>}
                      {doc.errorMessage && <span style={{ marginLeft: 6, color: '#DC2626' }} title={doc.errorMessage}>⚠</span>}
                    </div>
                    <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 2 }}>{doc.documentId}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button onClick={() => openDetail(doc.documentId)} style={{ padding: '3px 10px', borderRadius: 4, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 11 }}>查看</button>
                    <button onClick={() => handleReindex(doc.documentId)} style={{ padding: '3px 10px', borderRadius: 4, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 11 }}>重索引</button>
                    <button onClick={() => setDeleteTarget(doc.documentId)} style={{ padding: '3px 10px', borderRadius: 4, border: '1px solid #FCA5A5', background: '#FFF', color: '#DC2626', cursor: 'pointer', fontSize: 11 }}>删除</button>
                  </div>
                </div>
              ))}
              {/* Pagination */}
              {totalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'center', gap: 12, padding: '8px 0' }}>
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                    style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid #E5E7EB', background: page <= 1 ? '#F9FAFB' : '#FFF', cursor: page <= 1 ? 'not-allowed' : 'pointer', fontSize: 11 }}>
                    ← 上一页
                  </button>
                  <span style={{ fontSize: 11, color: '#6B7280', padding: '4px 0' }}>第 {page}/{totalPages} 页</span>
                  <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}
                    style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid #E5E7EB', background: page >= totalPages ? '#F9FAFB' : '#FFF', cursor: page >= totalPages ? 'not-allowed' : 'pointer', fontSize: 11 }}>
                    下一页 →
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Quick Questions */}
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 6 }}>快速提问</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {quickQs.map(q => (
                <button key={q} onClick={() => handleQuickQ(q)}
                  style={{ padding: '5px 12px', borderRadius: 10, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 11, color: '#6B7280' }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Ask Tab ── */}
      {tab === 'ask' && (
        <div>
          {askInput && (
            <div style={{ marginBottom: 8, padding: '8px 12px', borderRadius: 6, background: '#F0FDFA', fontSize: 12, color: '#0F766E', display: 'flex', justifyContent: 'space-between' }}>
              <span>已填入问题：{askInput}</span>
              <button onClick={() => setAskInput('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280', fontSize: 12 }}>✕</button>
            </div>
          )}
          <ChatWorkspace
            sessionId={activeSessionId}
            pendingCreate={!activeSessionId}
            defaultMode="rag"
            showFullModes={false}
            onSessionCreated={(id) => { onRefresh(); }}
            onConversationUpdate={onRefresh}
            onNewConversation={() => {}}
            view="qa"
            draftInput={askInput}
            onDraftConsumed={() => setAskInput('')}
          />
        </div>
      )}

      {/* ── Detail Modal ── */}
      {detailOpen && detailDoc && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', paddingTop: 40 }}
          onClick={() => setDetailOpen(false)}>
          <div onClick={e => e.stopPropagation()} style={{ background: '#FFF', borderRadius: 12, maxWidth: 700, width: '90%', maxHeight: '80vh', overflow: 'auto', padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={{ margin: 0, fontSize: 16 }}>{detailDoc.name}</h3>
              <button onClick={() => setDetailOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18 }}>✕</button>
            </div>
            <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 12, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <span>类型: {DOC_TYPE_LABELS[detailDoc.docType] || detailDoc.docType}</span>
              <span>状态: {DOC_STATUS_LABELS[detailDoc.status] || detailDoc.status}</span>
              <span>版本: v{detailDoc.version}</span>
              <span>Chunks: {detailDoc.chunkCount}</span>
              <span>Hash: {detailDoc.contentHash?.slice(0, 12)}...</span>
            </div>
            <div style={{ fontSize: 12, marginBottom: 12, background: '#F9FAFB', borderRadius: 6, padding: 10, maxHeight: 150, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
              {detailDoc.content?.slice(0, 2000)}{(detailDoc.content?.length ?? 0) > 2000 ? '...' : ''}
            </div>
            {detailChunks.length > 0 && (
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>分块 ({detailChunks.length})</div>
                {detailChunks.slice(0, 20).map(c => {
                  const isHighlighted = highlightChunkId && c.chunkId === highlightChunkId;
                  return (
                    <div key={c.chunkId} style={{
                      padding: '6px 8px', marginBottom: 4, borderRadius: 4,
                      background: isHighlighted ? '#F0FDFA' : '#F9FAFB',
                      border: isHighlighted ? '2px solid #0F766E' : '1px solid transparent',
                      fontSize: 11,
                    }}>
                      <div style={{ color: isHighlighted ? '#0F766E' : '#9CA3AF', fontWeight: isHighlighted ? 600 : 400 }}>
                        {isHighlighted && '★ 引用 '}#{c.chunkIndex} {c.sectionPath}
                      </div>
                      <div style={{ color: '#374151', marginTop: 2, maxHeight: 60, overflow: 'hidden' }}>{c.content.slice(0, 300)}</div>
                      <div style={{ color: '#D1D5DB', fontSize: 10 }}>{c.chunkId}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Ingest Modal ── */}
      {ingestOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', paddingTop: 60 }}
          onClick={() => setIngestOpen(false)}>
          <div onClick={e => e.stopPropagation()} style={{ background: '#FFF', borderRadius: 12, maxWidth: 600, width: '90%', padding: 20 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>添加知识</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <input placeholder="名称" value={ingestName}
                onChange={e => setIngestName(e.target.value)}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none' }} />
              <select value={ingestType} onChange={e => setIngestType(e.target.value)}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, background: '#FFF' }}>
                {Object.entries(DOC_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <textarea placeholder="Markdown / 文本内容" value={ingestContent}
                onChange={e => setIngestContent(e.target.value)} rows={10}
                style={{ padding: '8px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 12, resize: 'vertical', fontFamily: 'monospace' }} />
              {ingestError && <div style={{ color: '#DC2626', fontSize: 12 }}>{ingestError}</div>}
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button onClick={() => setIngestOpen(false)} style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12 }}>取消</button>
                <button onClick={handleIngest} disabled={ingesting || !ingestName.trim() || !ingestContent.trim()}
                  style={{ padding: '6px 16px', borderRadius: 6, border: 'none', background: ingesting ? '#D1D5DB' : '#0F766E', color: '#FFF', cursor: ingesting ? 'not-allowed' : 'pointer', fontSize: 12 }}>
                  {ingesting ? '创建中...' : '创建'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Confirm ── */}
      {deleteTarget && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000, display: 'flex', justifyContent: 'center', alignItems: 'center' }}
          onClick={() => setDeleteTarget(null)}>
          <div onClick={e => e.stopPropagation()} style={{ background: '#FFF', borderRadius: 12, padding: 24, maxWidth: 400, textAlign: 'center' }}>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>确认删除</div>
            <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 16 }}>这是软删除，删除后该文档将不再参与 RAG 检索。</div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <button onClick={() => setDeleteTarget(null)} style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12 }}>取消</button>
              <button onClick={handleDelete} disabled={deleting}
                style={{ padding: '6px 16px', borderRadius: 6, border: 'none', background: '#DC2626', color: '#FFF', cursor: deleting ? 'not-allowed' : 'pointer', fontSize: 12 }}>
                {deleting ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
