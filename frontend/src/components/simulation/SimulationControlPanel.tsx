/**
 * SimulationControlPanel — 仿真场景控制面板
 *
 * 模拟交通环境
 * SIMULATED DATA
 */

import React from 'react';
import type { SimulationScenario, SimulationRun, TrafficEvent } from '../../types/simulation';

interface Props {
  scenarios: SimulationScenario[];
  selectedScenarioId: string;
  onSelectScenario: (id: string) => void;
  onCreateSimulation: () => void;
  onInjectEvent: () => void;
  onReset: () => void;
  run: SimulationRun | null;
  events: TrafficEvent[];
  loading: boolean;
}

export const SimulationControlPanel: React.FC<Props> = ({
  scenarios,
  selectedScenarioId,
  onSelectScenario,
  onCreateSimulation,
  onInjectEvent,
  onReset,
  run,
  events,
  loading,
}) => {
  const hasRun = run !== null;
  const activeEvents = events.filter(e => e.status === 'active');

  return (
    <div style={{
      background: '#FFF', borderRadius: 12, border: '1px solid #E5E7EB',
      padding: 16, display: 'flex', flexDirection: 'column', gap: 12,
      minWidth: 240, maxWidth: 280,
    }}>
      {/* Header */}
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#111827' }}>
          🗺 交通态势
        </div>
        <div style={{
          fontSize: 10, color: '#EF4444', fontWeight: 600,
          background: '#FEF2F2', padding: '2px 6px', borderRadius: 4,
          display: 'inline-block', marginTop: 4,
        }}>
          SIMULATED DATA
        </div>
      </div>

      {/* Scenario Selector */}
      <div>
        <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4, fontWeight: 600 }}>
          预设场景
        </div>
        <select
          value={selectedScenarioId}
          onChange={e => onSelectScenario(e.target.value)}
          disabled={hasRun}
          style={{
            width: '100%', padding: '6px 10px', borderRadius: 8,
            border: '1px solid #E5E7EB', fontSize: 12, background: '#FFF',
            color: hasRun ? '#9CA3AF' : '#111827',
          }}
        >
          {scenarios.map(s => (
            <option key={s.scenarioId} value={s.scenarioId}>
              {s.name}
            </option>
          ))}
        </select>
        {scenarios.find(s => s.scenarioId === selectedScenarioId) && (
          <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 4, lineHeight: 1.4 }}>
            {scenarios.find(s => s.scenarioId === selectedScenarioId)!.description.slice(0, 100)}...
          </div>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {!hasRun ? (
          <button
            onClick={onCreateSimulation}
            disabled={loading}
            style={{
              width: '100%', padding: '8px 0', borderRadius: 8,
              border: 'none', background: loading ? '#D1D5DB' : '#0F766E',
              color: '#FFF', cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: 12, fontWeight: 600,
            }}
          >
            {loading ? '创建中...' : '🚀 创建仿真'}
          </button>
        ) : (
          <>
            <button
              onClick={onInjectEvent}
              disabled={loading}
              style={{
                width: '100%', padding: '8px 0', borderRadius: 8,
                border: 'none', background: loading ? '#D1D5DB' : '#DC2626',
                color: '#FFF', cursor: loading ? 'not-allowed' : 'pointer',
                fontSize: 12, fontWeight: 600,
              }}
            >
              {loading ? '注入中...' : '⚡ 注入事故 (演示大道R01)'}
            </button>

            <button
              onClick={onReset}
              disabled={loading}
              style={{
                width: '100%', padding: '8px 0', borderRadius: 8,
                border: '1px solid #E5E7EB', background: '#FFF',
                color: '#6B7280', cursor: loading ? 'not-allowed' : 'pointer',
                fontSize: 12,
              }}
            >
              🔄 重置仿真
            </button>
          </>
        )}
      </div>

      {/* Run Info */}
      {run && (
        <div style={{
          background: '#F9FAFB', borderRadius: 8, padding: 10,
          border: '1px solid #F3F4F6',
        }}>
          <div style={{ fontSize: 10, color: '#9CA3AF', fontWeight: 600, marginBottom: 4 }}>
            运行状态
          </div>
          <div style={{ fontSize: 11, color: '#374151', lineHeight: 1.6 }}>
            <div>Run ID: <span style={{ fontFamily: 'monospace', fontSize: 10 }}>{run.runId.slice(0, 20)}...</span></div>
            <div>场景: {run.scenarioId}</div>
            <div>快照: {run.snapshotCount}</div>
            <div>状态: <span style={{
              color: run.status === 'running' ? '#0F766E' : '#6B7280',
              fontWeight: 600,
            }}>{run.status}</span></div>
          </div>
        </div>
      )}

      {/* Active Events */}
      {activeEvents.length > 0 && (
        <div style={{
          background: '#FEF2F2', borderRadius: 8, padding: 10,
          border: '1px solid #FECACA',
        }}>
          <div style={{ fontSize: 10, color: '#DC2626', fontWeight: 600, marginBottom: 4 }}>
            活跃事件 ({activeEvents.length})
          </div>
          {activeEvents.map(evt => (
            <div key={evt.eventId} style={{ fontSize: 10, color: '#991B1B', lineHeight: 1.5 }}>
              <strong>{evt.eventType}</strong> · {evt.roadId}
              <br />{evt.description.slice(0, 60)}
            </div>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      <div style={{
        fontSize: 9, color: '#D1D5DB', textAlign: 'center',
        borderTop: '1px solid #F3F4F6', paddingTop: 8,
        lineHeight: 1.5,
      }}>
        模拟交通环境 · 非真实数据<br />
        所有标注均为 SIMULATED
      </div>
    </div>
  );
};
