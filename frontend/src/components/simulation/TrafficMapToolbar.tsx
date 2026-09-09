/**
 * TrafficMapToolbar — Simulation 控制工具栏
 */
import React from 'react';
import { BranchesOutlined, PlusCircleOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import type { SimulationScenario, SimulationRun } from '../../types/simulation';
import { visualTokens } from '../../styles/visualTokens';

const { color, radius } = visualTokens;

interface Props {
  scenarios: SimulationScenario[];
  selectedScenarioId: string;
  onSelectScenario: (id: string) => void;
  onCreateSimulation: () => void;
  onNewSimulation: () => void;
  onInjectEvent: () => void;
  onStartWorkflow: () => void;
  onReset: () => void;
  run: SimulationRun | null;
  hasActiveEvents: boolean;
  workflowRunId: string | null;
  workflowStatus: string | null;
  loading: boolean;
}

export const TrafficMapToolbar: React.FC<Props> = ({
  scenarios, selectedScenarioId, onSelectScenario, onCreateSimulation, onNewSimulation,
  onInjectEvent, onStartWorkflow, onReset, run, hasActiveEvents, workflowRunId, workflowStatus, loading,
}) => {
  const hasRun = run !== null;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 10, flexWrap: 'wrap', border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md, background: color.surfaceMuted, marginBottom: 12 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 138 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: color.text }}>演练模式</span>
        <span style={{ fontSize: 10, color: color.textMuted }}>路网视图 · 演练拓扑</span>
      </div>

      <select value={selectedScenarioId} onChange={e => onSelectScenario(e.target.value)}
        style={{ padding: '6px 10px', borderRadius: radius.sm, border: `1px solid ${color.border}`, fontSize: 12, background: color.surface, minWidth: 190, color: '#334155' }}>
        {scenarios.map(s => (<option key={s.scenarioId} value={s.scenarioId}>{scenarioName(s.name)}</option>))}
      </select>

      {!hasRun ? (
        <button onClick={onCreateSimulation} disabled={loading}
            className="traffic-control-button"
            style={btnStyle(loading ? '#94A3B8' : color.primary)}>
          <PlusCircleOutlined /> {loading ? '处理中' : '创建模拟运行'}
        </button>
      ) : (
        <>
          <button onClick={onNewSimulation} disabled={loading}
            className="traffic-control-button"
            style={btnOutlineStyle}><PlusCircleOutlined /> 新建模拟</button>
          <button onClick={onInjectEvent} disabled={loading}
            className="traffic-control-button"
            style={btnStyle(loading ? '#94A3B8' : color.danger)}>
            <WarningOutlined /> {loading ? '处理中' : '注入模拟事件'}
          </button>
          {hasActiveEvents && !workflowRunId && (
            <button onClick={onStartWorkflow} disabled={loading}
              className="traffic-control-button"
              style={btnStyle(loading ? '#94A3B8' : color.primary)}>
              <BranchesOutlined /> {loading ? '处理中' : 'TrafficMind 研判'}
            </button>
          )}
          <button onClick={onReset} disabled={loading}
            className="traffic-control-button"
            style={btnOutlineStyle}><ReloadOutlined /> 重置拓扑</button>
        </>
      )}

      {run && (
        <div style={{ display: 'flex', gap: 6, marginLeft: 'auto', alignItems: 'center', fontSize: 11, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <StatusChip label="快照" value={run.snapshotCount} />
          <StatusChip label="状态" value={statusLabel(run.status)} color={run.status === 'running' ? color.primary : undefined} />
          <span style={{ color: color.textMuted, background: color.surface, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.sm, padding: '2px 7px', fontWeight: 600, fontSize: 10 }}>演练拓扑</span>
        </div>
      )}
    </div>
  );
};

const StatusChip: React.FC<{ label: string; value: string | number; color?: string }> = ({ label, value, color: tone }) => (
  <span style={{ background: tone ? color.primarySoft : color.surface, border: `1px solid ${tone ? color.primaryBorder : color.borderSubtle}`, padding: '2px 8px', borderRadius: radius.sm, color: tone ?? color.textMuted, fontVariantNumeric: 'tabular-nums' }}>
    {label}: <strong style={{ fontWeight: 650 }}>{value}</strong>
  </span>
);

function statusLabel(s: string): string {
  const m: Record<string,string> = { created: '已创建', running: '运行中', completed: '已完成', reset: '已重置' };
  return m[s] ?? s;
}

function scenarioName(name: string): string {
  return name.replace(/^Scenario\s+[A-Z]:\s*/i, '');
}

const btnStyle = (bg: string): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 5,
  padding: '6px 12px', borderRadius: 6, border: 'none', background: bg,
  color: '#FFF', cursor: 'pointer', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
});

const btnOutlineStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  padding: '6px 12px', borderRadius: 6, border: '1px solid #CBD5E1', background: '#FFF',
  color: '#334155', cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap', fontWeight: 500,
};
