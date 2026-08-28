/**
 * RelatedWorkflowRuns — Phase 20 Round 2
 *
 * 轻量共用组件：按真实持久化关系查询相关 Workflow Runs。
 *  - session-level：workflow_runs.session_id == chat sessionId（复用 GET /workflow/runs?session_id=）
 *  - event-level：state_json $.currentEvent.eventId == eventId（复用 GET /workflow/runs?event_id=）
 *
 * 关系是「相关」而非「对应」：0..N 条，全部展示，绝不静默挑选 latest。
 */
import React, { useEffect, useState } from 'react';
import { listRuns } from '../../api/workflowApi';
import type { RunSummary } from '../../types/workflow';
import { RUN_STATUS_LABELS, RUN_STATUS_COLORS } from '../../types/workflow';

interface Props {
  sessionId?: string;
  eventId?: string;
  onOpenRun: (runId: string) => void;
}

export const RelatedWorkflowRuns: React.FC<Props> = ({ sessionId, eventId, onOpenRun }) => {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!sessionId && !eventId) {
      setRuns(null);
      return;
    }
    setRuns(null); setError(null);
    listRuns(sessionId ? { session_id: sessionId, limit: 50 } : { event_id: eventId, limit: 50 })
      .then(res => { if (!cancelled) setRuns(res.runs || []); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : '查询失败'); });
    return () => { cancelled = true; };
  }, [sessionId, eventId]);

  if (!sessionId && !eventId) return null;

  return (
    <div style={{ background: '#FFF', borderRadius: 12, border: '1px solid #E5E7EB', padding: '10px 14px', marginTop: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: '#111827', marginBottom: 6 }}>
        相关 Workflow Runs
        {runs !== null && <span style={{ fontWeight: 400, color: '#9CA3AF', marginLeft: 6 }}>（{runs.length}）</span>}
      </div>
      {error ? (
        <div style={{ fontSize: 11, color: '#DC2626' }}>查询失败：{error}</div>
      ) : runs === null ? (
        <div style={{ fontSize: 11, color: '#9CA3AF' }}>正在查询…</div>
      ) : runs.length === 0 ? (
        <div style={{ fontSize: 11, color: '#9CA3AF' }}>暂无相关运行</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {runs.map(r => (
            <button key={r.runId} onClick={() => onOpenRun(r.runId)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, textAlign: 'left',
                padding: '6px 10px', borderRadius: 8, border: '1px solid #E5E7EB',
                background: '#FFF', cursor: 'pointer', fontSize: 11,
              }}>
              <span style={{
                width: 8, height: 8, borderRadius: 4, flexShrink: 0,
                background: RUN_STATUS_COLORS[r.status] || '#9CA3AF',
              }} />
              <span style={{ color: '#6B7280', fontFamily: 'monospace' }}>{r.runId.slice(0, 12)}</span>
              <span style={{ color: '#374151' }}>{r.definitionName || r.definitionId.slice(0, 12) || '未知模板'}</span>
              <span style={{ color: RUN_STATUS_COLORS[r.status] || '#6B7280' }}>{RUN_STATUS_LABELS[r.status] || r.status}</span>
              <span style={{ color: '#9CA3AF', marginLeft: 'auto' }}>
                {r.startedAt ? new Date(r.startedAt).toLocaleString() : '未记录'}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
