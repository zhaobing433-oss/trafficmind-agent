/** 冲突与仲裁面板 */
import type { CollaborationConflict } from '../../types/collaboration';

export default function ConflictPanel({ conflicts }: { conflicts: CollaborationConflict[] }) {
  if (!conflicts || conflicts.length === 0) return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB', fontSize: 12, color: '#6B7280' }}>
      本次协作未发现需要仲裁的结论冲突。
    </div>
  );

  return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: '#111827' }}>冲突检测 ({conflicts.length})</div>
      {conflicts.map(c => (
        <div key={c.id} style={{
          padding: 10, marginBottom: 8, borderRadius: 12,
          background: c.severity === 'high' || c.severity === 'critical' ? '#FEF2F2' : '#FFFBEB',
          borderLeft: `3px solid ${c.severity === 'high' || c.severity === 'critical' ? '#EF4444' : '#F59E0B'}`,
          fontSize: 12,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>[{c.severity}] {c.type}</div>
          <div style={{ color: '#374151' }}>{c.description}</div>
          <div style={{ color: '#6B7280', fontSize: 11, marginTop: 2 }}>参与方: {c.participants.join(', ')}</div>
          {c.resolution && <div style={{ color: '#0F766E', marginTop: 4, fontWeight: 500 }}>→ {c.resolution}</div>}
          {c.requiresHumanReview && (
            <div style={{ color: '#EF4444', fontWeight: 700, marginTop: 4, fontSize: 11 }}>
              ⚠ 需要人工审核 — 当前建议不能作为确定执行命令
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
