/**
 * TrafficMapToolbar — Simulation 控制工具栏
 */
import React from 'react';
import type { SimulationScenario, SimulationRun } from '../../types/simulation';

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
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', flexWrap: 'wrap', borderBottom: '1px solid #E5E7EB', marginBottom: 8 }}>
      {/* Scenario selector */}
      <select value={selectedScenarioId} onChange={e => onSelectScenario(e.target.value)}
        style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 12, background: '#FFF', minWidth: 180 }}>
        {scenarios.map(s => (<option key={s.scenarioId} value={s.scenarioId}>{s.name}</option>))}
      </select>

      {/* Action buttons */}
      {!hasRun ? (
        <button onClick={onCreateSimulation} disabled={loading}
          style={btnStyle(loading ? '#9CA3AF' : '#0F766E')}>
          {loading ? '...' : '创建仿真'}
        </button>
      ) : (
        <>
          <button onClick={onNewSimulation} disabled={loading}
            style={btnOutlineStyle}>新建仿真</button>
          <button onClick={onInjectEvent} disabled={loading}
            style={btnStyle(loading ? '#9CA3AF' : '#DC2626')}>
            {loading ? '...' : '注入事故'}
          </button>
          {hasActiveEvents && !workflowRunId && (
            <button onClick={onStartWorkflow} disabled={loading}
              style={btnStyle(loading ? '#9CA3AF' : '#0F766E')}>
              {loading ? '...' : 'TrafficMind 研判'}
            </button>
          )}
          <button onClick={onReset} disabled={loading}
            style={btnOutlineStyle}>重置</button>
        </>
      )}

      {/* Status chips */}
      {run && (
        <div style={{ display: 'flex', gap: 6, marginLeft: 'auto', alignItems: 'center', fontSize: 11, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <StatusChip label="快照" value={run.snapshotCount} />
          <StatusChip label="状态" value={statusLabel(run.status)} color={run.status === 'running' ? '#0F766E' : undefined} />
          <span style={{ color: '#EF4444', fontWeight: 700, fontSize: 10, marginLeft: 4 }}>SIMULATED</span>
        </div>
      )}
    </div>
  );
};

const StatusChip: React.FC<{ label: string; value: string | number; color?: string }> = ({ label, value, color }) => (
  <span style={{ background: '#F3F4F6', padding: '2px 8px', borderRadius: 10, color: color ?? '#6B7280' }}>
    {label}: <strong>{value}</strong>
  </span>
);

function statusLabel(s: string): string {
  const m: Record<string,string> = { created: '已创建', running: '运行中', completed: '已完成', reset: '已重置' };
  return m[s] ?? s;
}

const btnStyle = (bg: string): React.CSSProperties => ({
  padding: '5px 14px', borderRadius: 6, border: 'none', background: bg,
  color: '#FFF', cursor: 'pointer', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
});

const btnOutlineStyle: React.CSSProperties = {
  padding: '5px 14px', borderRadius: 6, border: '1px solid #D1D5DB', background: '#FFF',
  color: '#374151', cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap',
};
