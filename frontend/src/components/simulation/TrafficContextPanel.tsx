/**
 * TrafficContextPanel — 右侧上下文面板: Event / Agent / Workflow
 */
import React, { useEffect, useState } from 'react';
import type { TrafficSnapshot, TrafficEvent, SimulationRun } from '../../types/simulation';

interface Proposal {
  actionType?: string; sourceRoadId?: string; targetRoadIds?: string[];
  diversionRatio?: number; rationale?: string; evidenceRefs?: string[];
  simulation?: boolean; source?: string;
}

interface Props {
  snapshot: TrafficSnapshot | null; events: TrafficEvent[]; run: SimulationRun | null;
  workflowRunId: string | null; workflowStatus: string | null;
  onApprove?: () => void; onReject?: () => void; onViewWorkflow?: () => void;
  beforeSnapshot?: TrafficSnapshot | null;
}

export const TrafficContextPanel: React.FC<Props> = ({ snapshot, events, run, workflowRunId, workflowStatus, onApprove, onReject, onViewWorkflow, beforeSnapshot }) => {
  const activeEvents = events.filter(e => e.status === 'active');
  const roadStates = snapshot?.roadStates ?? {};
  const mainEvent = activeEvents[0];
  const mainRoadId = mainEvent?.roadId ?? 'R01';
  const roadState = roadStates[mainRoadId];
  const [proposal, setProposal] = useState<Proposal | null>(null);

  // Fetch proposal from workflow when awaiting_approval
  useEffect(() => {
    if (!workflowRunId || workflowStatus !== 'awaiting_approval') { setProposal(null); return; }
    let cancelled = false;
    fetch(`/api/workflow/runs/${encodeURIComponent(workflowRunId)}`).then(r => r.json()).then(data => {
      if (cancelled) return;
      const pa = (data.state as Record<string,unknown>)?.proposedActions;
      const arr = Array.isArray(pa) ? pa : [];
      const first = arr.find((a: Record<string,unknown>) => a?.actionType === 'traffic_diversion' || a?.actionType);
      if (first) setProposal(first as unknown as Proposal);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [workflowRunId, workflowStatus]);

  // Before/after comparison
  const beforeRs = beforeSnapshot?.roadStates?.[mainRoadId];
  const showImprovement = workflowStatus === 'completed' && beforeRs && roadState &&
    (roadState.avgSpeed !== beforeRs.avgSpeed || roadState.queueLength !== beforeRs.queueLength);

  return (
    <div style={{ width: 340, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12 }}>
      {/* A. Event Situation */}
      <Section title="当前事件" color="#DC2626">
        {mainEvent ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div><strong>{eventLabel(mainEvent.eventType)}</strong> · {mainRoadId}</div>
            <MetricRow label="拥堵等级" value={congLabel(roadState?.congestionLevel)} color={congColor(roadState?.congestionLevel)} />
            <MetricRow label="平均速度" value={`${roadState?.avgSpeed ?? '—'} km/h`} />
            <MetricRow label="排队长度" value={`${roadState?.queueLength ?? '—'} m`} />
            <MetricRow label="占有率" value={roadState?.occupancy != null ? `${(roadState.occupancy * 100).toFixed(0)}%` : '—'} />
            <MetricRow label="活跃事件" value={activeEvents.length} />
          </div>
        ) : (
          <Muted>无活跃事件 — 点击「注入事故」创建模拟事件</Muted>
        )}
      </Section>

      {/* B. Agent Recommendation */}
      <Section title="Agent 研判" color="#0F766E">
        {!workflowRunId ? (
          <Muted>等待启动 TrafficMind 研判</Muted>
        ) : workflowStatus === 'running' ? (
          <Muted>Agent 分析中...</Muted>
        ) : workflowStatus === 'awaiting_approval' ? (
          proposal ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ fontWeight: 600 }}>CongestionAgent</div>
              <div style={{ color: '#374151' }}>建议: <strong>交通分流</strong></div>
              <div style={{ fontSize: 11, color: '#6B7280' }}>
                {proposal.sourceRoadId} → {(proposal.targetRoadIds ?? []).join(' / ')}
              </div>
              <div>分流比例: <strong>{((proposal.diversionRatio ?? 0) * 100).toFixed(0)}%</strong></div>
              {proposal.rationale && <Rationale text={proposal.rationale} />}
              {(proposal.evidenceRefs ?? []).length > 0 && (
                <div style={{ fontSize: 10, color: '#9CA3AF' }}>证据: {(proposal.evidenceRefs ?? []).join(', ')}</div>
              )}
            </div>
          ) : (
            <Muted>Agent 已提出处置建议，等待审批</Muted>
          )
        ) : workflowStatus === 'completed' ? (
          showImprovement ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <div style={{ fontWeight: 600, color: '#0F766E' }}>处置完成</div>
              <div style={{ fontSize: 11, color: '#6B7280', marginTop: 4, fontWeight: 600 }}>处置效果</div>
              <MetricRow label="速度" value={`${beforeRs!.avgSpeed} → ${roadState!.avgSpeed} km/h`} color={roadState!.avgSpeed > beforeRs!.avgSpeed ? '#0F766E' : undefined} />
              <MetricRow label="排队" value={`${beforeRs!.queueLength} → ${roadState!.queueLength} m`} color={roadState!.queueLength < beforeRs!.queueLength ? '#0F766E' : undefined} />
              <MetricRow label="拥堵" value={`${congLabel(beforeRs!.congestionLevel)} → ${congLabel(roadState!.congestionLevel)}`} color="#0F766E" />
            </div>
          ) : (
            <Muted>处置已完成</Muted>
          )
        ) : workflowStatus === 'rejected' ? (
          <Muted>处置建议已驳回</Muted>
        ) : (
          <Muted>状态: {workflowStatus ?? '—'}</Muted>
        )}
      </Section>

      {/* C. Workflow Control */}
      <Section title="工作流" color="#3B82F6">
        {workflowRunId ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: 10, color: '#6B7280' }}>{workflowRunId.slice(0, 16)}...</div>
            <div style={{ fontWeight: 600, color: statusColor(workflowStatus) }}>{statusLabel(workflowStatus)}</div>
            {workflowStatus === 'awaiting_approval' && (
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={onApprove} style={approveBtn}>批准</button>
                <button onClick={onReject} style={rejectBtn}>驳回</button>
              </div>
            )}
            {onViewWorkflow && workflowRunId && (
              <button onClick={onViewWorkflow} style={{ ...rejectBtn, color: '#3B82F6', borderColor: '#3B82F6' }}>查看完整工作流 →</button>
            )}
          </div>
        ) : (
          <Muted>尚未创建 Workflow</Muted>
        )}
      </Section>
    </div>
  );
};

// ── Sub-components ─────────────────────────────────────────────────

const Rationale: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ fontSize: 10, color: '#6B7280', background: '#F9FAFB', borderRadius: 6, padding: '6px 8px', marginTop: 2, lineHeight: 1.5, maxHeight: 80, overflow: 'hidden' }}>{text}</div>
);

const Section: React.FC<{ title: string; color: string; children: React.ReactNode }> = ({ title, color, children }) => (
  <div style={{ background: '#FFF', borderRadius: 10, border: '1px solid #E5E7EB', padding: '12px 14px' }}>
    <div style={{ fontSize: 11, fontWeight: 700, color, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>{title}</div>
    {children}
  </div>
);

const MetricRow: React.FC<{ label: string; value: string | number; color?: string }> = ({ label, value, color }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', color: '#374151' }}>
    <span style={{ color: '#9CA3AF' }}>{label}</span>
    <span style={{ fontWeight: 600, color: color ?? '#111827' }}>{value}</span>
  </div>
);

const Muted: React.FC<{ children: React.ReactNode }> = ({ children }) => (<div style={{ color: '#9CA3AF', fontSize: 11 }}>{children}</div>);

function eventLabel(t: string): string { const m: Record<string,string> = { accident: '交通事故', congestion: '拥堵', construction: '施工', vehicle_stopped: '车辆滞留' }; return m[t] ?? t; }
function congLabel(c?: string): string { const m: Record<string,string> = { normal: '正常', slow: '缓行', congested: '拥堵', severe: '严重拥堵' }; return m[c ?? ''] ?? (c ?? '—'); }
function congColor(c?: string): string { const m: Record<string,string> = { normal: '#22C55E', slow: '#F59E0B', congested: '#F97316', severe: '#EF4444' }; return m[c ?? ''] ?? '#6B7280'; }
function statusColor(s: string | null): string { const m: Record<string,string> = { running: '#3B82F6', awaiting_approval: '#F59E0B', completed: '#0F766E', failed: '#EF4444', rejected: '#EF4444' }; return m[s ?? ''] ?? '#6B7280'; }
function statusLabel(s: string | null): string { const m: Record<string,string> = { running: '分析中', awaiting_approval: '等待审批', completed: '已完成', failed: '失败', rejected: '已驳回' }; return m[s ?? ''] ?? (s ?? '—'); }

const approveBtn: React.CSSProperties = { flex: 1, padding: '6px 0', borderRadius: 6, border: 'none', background: '#0F766E', color: '#FFF', cursor: 'pointer', fontSize: 12, fontWeight: 600 };
const rejectBtn: React.CSSProperties = { flex: 1, padding: '6px 0', borderRadius: 6, border: '1px solid #EF4444', background: '#FFF', color: '#EF4444', cursor: 'pointer', fontSize: 12, fontWeight: 600 };
