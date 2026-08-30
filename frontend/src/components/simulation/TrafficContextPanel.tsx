import React, { useEffect, useState } from 'react';
import type { TrafficSnapshot, TrafficEvent, SimulationRun } from '../../types/simulation';
import { visualTokens } from '../../styles/visualTokens';

const { color, radius, shadow, font } = visualTokens;

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
    <div className="traffic-context-rail" style={{ flex: '0 0 340px', width: '100%', maxWidth: 340, minWidth: 280, display: 'flex', flexDirection: 'column', gap: 0, fontSize: 12, background: color.surface, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md, padding: 12, color: color.text, boxShadow: shadow.subtle }}>
      <div style={{ padding: '2px 2px 12px', marginBottom: 2, borderBottom: `1px solid ${color.borderSubtle}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 15, color: color.text, fontWeight: 600 }}>当前处置</span>
          <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: radius.sm, background: color.surfaceMuted, color: color.textMuted, border: `1px solid ${color.borderSubtle}`, fontWeight: 500 }}>演练模式</span>
        </div>
        <div style={{ marginTop: 5, fontSize: 12, color: color.textMuted }}>
          {run ? `${statusLabel(run.status)} · ${run.createdAt ? new Date(run.createdAt).toLocaleTimeString() : '时间未记录'}` : '创建模拟运行后展示研判与工作流状态'}
        </div>
      </div>
      <PipelineSection stage="事件" status={mainEvent ? eventLabel(mainEvent.eventType) : '未触发'} tone="#D9732D">
        {mainEvent ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div><strong style={{ fontWeight: 600 }}>{eventLabel(mainEvent.eventType)}</strong><span style={{ color: color.textSubtle }}> · 路段 {mainRoadId}</span></div>
            <MetricRow label="拥堵等级" value={congLabel(roadState?.congestionLevel)} color={congColor(roadState?.congestionLevel)} />
            <MetricRow label="平均速度" value={`${roadState?.avgSpeed ?? '—'} km/h`} />
            <MetricRow label="排队长度" value={`${roadState?.queueLength ?? '—'} m`} />
            <MetricRow label="占有率" value={roadState?.occupancy != null ? `${(roadState.occupancy * 100).toFixed(0)}%` : '—'} />
            <MetricRow label="活跃事件" value={activeEvents.length} />
          </div>
        ) : (
          <Muted>模拟拓扑暂无活跃事件</Muted>
        )}
      </PipelineSection>

      <FlowConnector />
      <PipelineSection stage="研判" status={workflowStatus === 'running' ? '运行中' : workflowStatus === 'awaiting_approval' ? '待审批' : workflowRunId ? '已绑定' : '未启动'} tone={color.primary} active={workflowStatus === 'running'}>
        {!workflowRunId ? (
          <Muted>等待启动 TrafficMind 研判</Muted>
        ) : !workflowStatus ? (
          <Muted>已绑定工作流；进入详情可查看真实执行状态。</Muted>
        ) : workflowStatus === 'running' ? (
          <Muted>正在分析事件影响与处置路径</Muted>
        ) : workflowStatus === 'awaiting_approval' ? (
          proposal ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ color: color.text }}>建议：<strong style={{ fontWeight: 600 }}>交通分流</strong></div>
              <div style={{ fontSize: 11, color: color.textMuted }}>
                {proposal.sourceRoadId} → {(proposal.targetRoadIds ?? []).join(' / ')}
              </div>
              <div>分流比例: <strong>{((proposal.diversionRatio ?? 0) * 100).toFixed(0)}%</strong></div>
              {proposal.rationale && <Rationale text={proposal.rationale} />}
              {(proposal.evidenceRefs ?? []).length > 0 && (
                <div style={{ fontSize: 11, color: color.textMuted }}>证据：{(proposal.evidenceRefs ?? []).join(', ')}</div>
              )}
            </div>
          ) : (
            <Muted>已提出处置建议，等待审批</Muted>
          )
        ) : workflowStatus === 'completed' ? (
          showImprovement ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <div style={{ fontWeight: 600, color: color.primary }}>处置完成</div>
              <div style={{ fontSize: 11, color: color.textMuted, marginTop: 4, fontWeight: 600 }}>处置效果</div>
              <MetricRow label="速度" value={`${beforeRs!.avgSpeed} → ${roadState!.avgSpeed} km/h`} color={roadState!.avgSpeed > beforeRs!.avgSpeed ? color.primary : undefined} />
              <MetricRow label="排队" value={`${beforeRs!.queueLength} → ${roadState!.queueLength} m`} color={roadState!.queueLength < beforeRs!.queueLength ? color.primary : undefined} />
              <MetricRow label="拥堵" value={`${congLabel(beforeRs!.congestionLevel)} → ${congLabel(roadState!.congestionLevel)}`} color={color.primary} />
            </div>
          ) : (
            <Muted>处置已完成</Muted>
          )
        ) : workflowStatus === 'rejected' ? (
          <Muted>处置建议已驳回</Muted>
        ) : (
          <Muted>状态: {workflowStatus ?? '—'}</Muted>
        )}
      </PipelineSection>

      <FlowConnector />
      <PipelineSection stage="处置计划" status="未关联" tone="#A0A7B2">
        <Muted>暂未关联处置方案；如存在真实执行记录，将在处置方案中心展示。</Muted>
      </PipelineSection>

      <FlowConnector />
      <PipelineSection stage="工作流" status={workflowRunId ? statusLabel(workflowStatus) : '未创建'} tone={workflowStatus === 'awaiting_approval' ? '#B7791F' : color.primary} active={workflowStatus === 'awaiting_approval'}>
        {workflowRunId ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontWeight: 700, color: statusColor(workflowStatus) }}>{statusLabel(workflowStatus)}</div>
            {workflowStatus === 'awaiting_approval' && (
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={onApprove} style={approveBtn}>批准</button>
                <button onClick={onReject} style={rejectBtn}>驳回</button>
              </div>
            )}
            {onViewWorkflow && workflowRunId && (
              <button onClick={onViewWorkflow} style={{ ...secondaryBtn }}>查看完整工作流</button>
            )}
            <details style={{ marginTop: 2, color: color.textSubtle }}>
              <summary style={{ cursor: 'pointer', fontSize: 11 }}>技术信息</summary>
              <div style={{ marginTop: 5, fontSize: 10, fontFamily: font.mono, color: color.textMuted, wordBreak: 'break-all' }}>
                工作流编号: {workflowRunId}
                {run?.runId ? <><br />演练编号: {run.runId}</> : null}
              </div>
            </details>
          </div>
        ) : (
          <Muted>尚未创建工作流</Muted>
        )}
      </PipelineSection>
    </div>
  );
};

// ── Sub-components ─────────────────────────────────────────────────

const Rationale: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ fontSize: 11, color: color.textMuted, background: color.surfaceMuted, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.sm, padding: '6px 8px', marginTop: 2, lineHeight: 1.5, maxHeight: 80, overflow: 'hidden' }}>{text}</div>
);

const PipelineSection: React.FC<{ stage: string; status: string; tone: string; active?: boolean; children: React.ReactNode }> = ({ stage, status, tone, active, children }) => (
  <div style={{ position: 'relative', background: active ? color.primarySoft : color.surface, borderRadius: radius.md, border: `1px solid ${active ? color.primaryBorder : color.borderSubtle}`, padding: '10px 12px 11px 34px' }}>
    <span style={{ position: 'absolute', left: 12, top: 13, width: 9, height: 9, borderRadius: 999, background: tone, opacity: active ? 1 : 0.72 }} />
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 7 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: color.text, letterSpacing: 0 }}>{stage}</div>
      <div style={{ fontSize: 11, fontWeight: 600, color: tone, whiteSpace: 'nowrap' }}>{status}</div>
    </div>
    {children}
  </div>
);

const FlowConnector: React.FC = () => (
  <div style={{ height: 10, borderLeft: `1px solid ${color.border}`, marginLeft: 17 }} />
);

const MetricRow: React.FC<{ label: string; value: string | number; color?: string }> = ({ label, value, color: tone }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', color: color.text, gap: 10 }}>
    <span style={{ color: color.textMuted }}>{label}</span>
    <span style={{ fontWeight: 650, color: tone ?? color.text, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
  </div>
);

const Muted: React.FC<{ children: React.ReactNode }> = ({ children }) => (<div style={{ color: color.textMuted, fontSize: 11, lineHeight: 1.6 }}>{children}</div>);

function eventLabel(t: string): string { const m: Record<string,string> = { accident: '交通事故', congestion: '拥堵', construction: '施工', vehicle_stopped: '车辆滞留' }; return m[t] ?? t; }
function congLabel(c?: string): string { const m: Record<string,string> = { normal: '正常', slow: '缓行', congested: '拥堵', severe: '严重拥堵' }; return m[c ?? ''] ?? (c ?? '—'); }
function congColor(c?: string): string { const m: Record<string,string> = { normal: color.primary, slow: '#B7791F', congested: '#C05621', severe: '#B91C1C' }; return m[c ?? ''] ?? color.textMuted; }
function statusColor(s: string | null): string { const m: Record<string,string> = { running: color.primary, awaiting_approval: '#B7791F', completed: color.primary, failed: '#B91C1C', rejected: '#B91C1C' }; return m[s ?? ''] ?? color.textMuted; }
function statusLabel(s: string | null): string { const m: Record<string,string> = { running: '分析中', awaiting_approval: '等待审批', completed: '已完成', failed: '失败', rejected: '已驳回' }; return m[s ?? ''] ?? (s ?? '已绑定'); }

const approveBtn: React.CSSProperties = { flex: 1, padding: '6px 0', borderRadius: radius.sm, border: 'none', background: color.primary, color: '#FFF', cursor: 'pointer', fontSize: 12, fontWeight: 600 };
const rejectBtn: React.CSSProperties = { flex: 1, padding: '6px 0', borderRadius: radius.sm, border: `1px solid ${color.border}`, background: '#FFF', color: color.textMuted, cursor: 'pointer', fontSize: 12, fontWeight: 500 };
const secondaryBtn: React.CSSProperties = { padding: '6px 0', borderRadius: radius.sm, border: `1px solid ${color.primaryBorder}`, background: color.primarySoft, color: color.primary, cursor: 'pointer', fontSize: 12, fontWeight: 600 };
