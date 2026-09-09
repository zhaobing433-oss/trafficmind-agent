/**
 * RelatedWorkflowRuns — Phase 20 Round 2
 *
 * 轻量共用组件：按真实持久化关系查询相关 Workflow Runs。
 *  - session-level：workflow_runs.session_id == chat sessionId（复用 GET /workflow/runs?session_id=）
 *  - event-level：state_json $.currentEvent.eventId == eventId（复用 GET /workflow/runs?event_id=）
 *
 * 关系是「相关」而非「对应」：0..N 条，全部展示，绝不静默挑选 latest。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { listRuns } from '../../api/workflowApi';
import type { RunSummary } from '../../types/workflow';
import { RUN_STATUS_LABELS, RUN_STATUS_COLORS } from '../../types/workflow';

const PAGE_SIZE = 50;

interface Props {
  sessionId?: string;
  eventId?: string;
  onOpenRun: (runId: string) => void;
}

export const RelatedWorkflowRuns: React.FC<Props> = ({ sessionId, eventId, onOpenRun }) => {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSeqRef = useRef(0);
  const relationKind = sessionId ? 'session' : eventId ? 'event' : null;
  const relationValue = sessionId || eventId || '';

  const fetchPage = useCallback((offset: number) => {
    if (!relationKind || !relationValue) return;
    const requestSeq = ++requestSeqRef.current;
    if (offset === 0) {
      setRuns(null);
      setTotal(null);
      setError(null);
    }
    setLoading(true);
    const params = relationKind === 'session'
      ? { session_id: relationValue, limit: PAGE_SIZE, offset }
      : { event_id: relationValue, limit: PAGE_SIZE, offset };
    listRuns(params)
      .then(res => {
        if (requestSeq !== requestSeqRef.current) return;
        const page = res.runs || [];
        setTotal(typeof res.total === 'number' ? res.total : offset + page.length);
        setRuns(prev => offset === 0 ? page : mergeRuns(prev || [], page));
      })
      .catch((e: unknown) => {
        if (requestSeq === requestSeqRef.current) setError(e instanceof Error ? e.message : '查询失败');
      })
      .finally(() => {
        if (requestSeq === requestSeqRef.current) setLoading(false);
      });
  }, [relationKind, relationValue]);

  useEffect(() => {
    if (!sessionId && !eventId) {
      requestSeqRef.current += 1;
      setRuns(null);
      setTotal(null);
      setError(null);
      return;
    }
    fetchPage(0);
  }, [sessionId, eventId, fetchPage]);

  if (!sessionId && !eventId) return null;
  const visibleCount = runs?.length ?? 0;
  const totalCount = total ?? visibleCount;
  const hasMore = runs !== null && total !== null && visibleCount < total;

  return (
    <div style={{ background: '#FFF', borderRadius: 8, border: '1px solid #E5E7EB', padding: '10px 14px', marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#111827' }}>
          相关工作流
          {runs !== null && <span style={{ fontWeight: 400, color: '#9CA3AF', marginLeft: 6 }}>共 {totalCount} 条</span>}
        </div>
        {hasMore && <span style={{ fontSize: 10, color: '#D97706' }}>当前显示 {visibleCount} / 共 {totalCount}</span>}
      </div>
      {error ? (
        <div style={{ fontSize: 11, color: '#DC2626' }}>查询失败：{error}</div>
      ) : runs === null || (loading && visibleCount === 0) ? (
        <div style={{ fontSize: 11, color: '#9CA3AF' }}>正在查询…</div>
      ) : runs.length === 0 ? (
        <div style={{ fontSize: 11, color: '#9CA3AF' }}>暂无相关运行</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {runs.map(r => (
            <button key={r.runId} onClick={() => onOpenRun(r.runId)}
              title={`工作流技术编号 ${r.runId}`}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, textAlign: 'left',
                padding: '6px 10px', borderRadius: 8, border: '1px solid #E5E7EB',
                background: '#FFF', cursor: 'pointer', fontSize: 11,
              }}>
              <span style={{
                width: 8, height: 8, borderRadius: 4, flexShrink: 0,
                background: RUN_STATUS_COLORS[r.status] || '#9CA3AF',
              }} />
              <span style={{ color: '#374151', fontWeight: 500 }}>{r.definitionName || r.definitionId.slice(0, 12) || '未知模板'}</span>
              <span style={{ color: RUN_STATUS_COLORS[r.status] || '#6B7280' }}>{RUN_STATUS_LABELS[r.status] || r.status}</span>
              <span style={{ color: '#9CA3AF', marginLeft: 'auto' }}>
                {r.startedAt ? new Date(r.startedAt).toLocaleString() : '未记录'}
              </span>
            </button>
          ))}
          {hasMore && (
            <button onClick={() => fetchPage(visibleCount)} disabled={loading}
              style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #E5E7EB', background: loading ? '#F9FAFB' : '#FFF', cursor: loading ? 'not-allowed' : 'pointer', fontSize: 11, color: '#6B7280' }}>
              {loading ? '正在加载...' : `继续加载（当前 ${visibleCount} / 共 ${totalCount}）`}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

function mergeRuns(existing: RunSummary[], incoming: RunSummary[]): RunSummary[] {
  const byId = new Map<string, RunSummary>();
  for (const run of existing) byId.set(run.runId, run);
  for (const run of incoming) byId.set(run.runId, run);
  return Array.from(byId.values());
}
