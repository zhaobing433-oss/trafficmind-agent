/** DAG 任务图 — 分层展示 */
import type { CollaborationTask } from '../../types/collaboration';
import { TASK_STATUS_LABELS } from '../../types/collaboration';

const STATUS_COLORS: Record<string, string> = {
  pending: '#D1D5DB', ready: '#93C5FD', running: '#60A5FA', succeeded: '#10B981',
  retrying: '#F59E0B', failed: '#EF4444', timed_out: '#F97316', blocked: '#6B7280', skipped: '#D1D5DB',
};

const LAYERS: Record<string, number> = {
  CongestionAgent: 0, SignalAgent: 0, PublicSafetyAgent: 0, AccidentAgent: 0,
  DispatchAgent: 1, ConflictDetector: 2, ConflictArbiter: 3, FusionAgent: 4,
};

export default function CollaborationDagView({ tasks }: { tasks: CollaborationTask[] }) {
  if (!tasks.length) return null;

  // Group by layer
  const layers: Record<number, CollaborationTask[]> = {};
  tasks.forEach(t => {
    const layer = LAYERS[t.agentName] ?? 0;
    (layers[layer] ||= []).push(t);
  });

  return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: '#111827' }}>任务图</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {Object.entries(layers).sort(([a], [b]) => Number(a) - Number(b)).map(([layer, layerTasks]) => (
          <div key={layer} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10, color: '#9CA3AF', width: 60, textAlign: 'right', flexShrink: 0 }}>第{Number(layer) + 1}层</span>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {layerTasks.map(t => (
                <div key={t.taskId} style={{
                  padding: '6px 10px', borderRadius: 10, border: `2px solid ${STATUS_COLORS[t.status] || '#D1D5DB'}`,
                  background: t.status === 'running' ? '#EFF6FF' : '#FFF', fontSize: 11, minWidth: 100, textAlign: 'center',
                  opacity: t.status === 'skipped' ? 0.5 : 1,
                }}>
                  <div style={{ fontWeight: 600, color: '#374151' }}>{t.agentName}</div>
                  <div style={{ color: STATUS_COLORS[t.status], fontWeight: 500, fontSize: 10 }}>
                    {TASK_STATUS_LABELS[t.status] || t.status}
                    {t.attempt > 1 && <span style={{ marginLeft: 4 }}>#{t.attempt}</span>}
                  </div>
                  {t.error && <div style={{ color: '#EF4444', fontSize: 9 }}>{t.error.slice(0, 30)}</div>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
