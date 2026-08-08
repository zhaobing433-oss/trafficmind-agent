/**
 * TrafficMapWorkspace — Phase 13 主页面
 *
 * 布局:
 * ┌──────────────────────────────────────────────────┐
 * │ 控制面板        │         地图                    │
 * │ 场景选择        │  道路/路口/摄像头/事件           │
 * │ 注入事件        │  拥堵状态着色                   │
 * │ 重置            │                                │
 * │                 ├────────────────────────────────│
 * │                 │ 底部状态栏 + 选中详情            │
 * └──────────────────────────────────────────────────┘
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { TrafficMapView } from './TrafficMapView';
import { SimulationControlPanel } from './SimulationControlPanel';
import {
  listScenarios,
  createSimulation,
  getSimulation,
  getNetwork,
  getSnapshot,
  injectEvent,
  resetSimulation,
} from '../../api/simulationApi';
import type {
  SimulationScenario,
  SimulationRun,
  TrafficSnapshot,
  TrafficRoadState,
  TrafficEvent,
} from '../../types/simulation';

// ── Component ──────────────────────────────────────────────────────

export const TrafficMapWorkspace: React.FC = () => {
  // ── State ────────────────────────────────────────────────────────
  const [scenarios, setScenarios] = useState<SimulationScenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('scenario_c_accident');
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [networkGeoJSON, setNetworkGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [snapshot, setSnapshot] = useState<TrafficSnapshot | null>(null);
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail panels
  const [selectedRoad, setSelectedRoad] = useState<{
    roadId: string; state: TrafficRoadState;
  } | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);

  const runIdRef = useRef<string>('');

  // ── Load scenarios ───────────────────────────────────────────────
  useEffect(() => {
    listScenarios()
      .then(res => {
        setScenarios(res.scenarios);
        if (res.scenarios.length > 0) {
          setSelectedScenarioId(res.scenarios[0].scenarioId);
        }
      })
      .catch(err => setError(`加载场景失败: ${err.message}`));
  }, []);

  // ── Restore from URL ─────────────────────────────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlRunId = params.get('simulationRunId');
    if (urlRunId && !runIdRef.current) {
      restoreSimulation(urlRunId);
    }
  }, []);

  const restoreSimulation = async (runId: string) => {
    try {
      setLoading(true);
      const [detail, network] = await Promise.all([
        getSimulation(runId),
        getNetwork(runId),
      ]);
      setNetworkGeoJSON(network);
      if (detail.snapshot) {
        setSnapshot(detail.snapshot as TrafficSnapshot);
      }
      setRun(detail.run as unknown as SimulationRun);
      setEvents((detail.events || []) as unknown as TrafficEvent[]);
      runIdRef.current = runId;
      updateUrl(runId);
    } catch (err) {
      setError(`恢复失败: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const updateUrl = useCallback((runId?: string) => {
    const url = new URL(window.location.href);
    if (runId) {
      url.searchParams.set('simulationRunId', runId);
    }
    window.history.replaceState({}, '', url.toString());
  }, []);

  // ── Actions ──────────────────────────────────────────────────────

  const handleCreateSimulation = async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await createSimulation(selectedScenarioId);
      setNetworkGeoJSON(res.network);
      setSnapshot(res.snapshot);
      setRun(res.run);
      setEvents([]);
      runIdRef.current = res.run.runId;
      updateUrl(res.run.runId);
    } catch (err) {
      setError(`创建失败: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleInjectEvent = async () => {
    if (!run) return;
    setError(null);
    setLoading(true);
    try {
      const scenario = scenarios.find(s => s.scenarioId === selectedScenarioId);
      const eventDef = scenario?.initialEvents?.[0];
      const res = await injectEvent(run.runId, {
        eventType: eventDef?.event_type as string || 'accident',
        severity: eventDef?.severity as string || 'high',
        roadId: eventDef?.road_id as string || 'R01',
        longitude: eventDef?.longitude as number || 116.397,
        latitude: eventDef?.latitude as number || 39.907,
        description: eventDef?.description as string || '模拟交通事故',
      });
      setSnapshot(res.snapshot);
      setEvents(prev => [...prev, res.event]);

      // Refresh run info
      const detail = await getSimulation(run.runId);
      setRun(detail.run as unknown as SimulationRun);
    } catch (err) {
      setError(`事件注入失败: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (!run) return;
    setError(null);
    setLoading(true);
    try {
      const res = await resetSimulation(run.runId);
      setSnapshot(res.snapshot);
      setEvents([]);
      setSelectedRoad(null);
      setSelectedCameraId(null);

      // Refresh
      const detail = await getSimulation(run.runId);
      setRun(detail.run as unknown as SimulationRun);
    } catch (err) {
      setError(`重置失败: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  // ── Map callbacks ────────────────────────────────────────────────

  const handleRoadClick = useCallback((roadId: string, state: TrafficRoadState) => {
    setSelectedRoad({ roadId, state });
    setSelectedCameraId(null);
  }, []);

  const handleCameraClick = useCallback((cameraId: string) => {
    setSelectedCameraId(cameraId);
    setSelectedRoad(null);
  }, []);

  // ── Get road name ───────────────────────────────────────────────
  const getRoadName = (roadId: string): string => {
    if (!networkGeoJSON) return roadId;
    const feat = networkGeoJSON.features.find(
      f => f.properties?.roadId === roadId || f.properties?.road_id === roadId,
    );
    return (feat?.properties?.name as string) || (feat?.properties?.road_name as string) || roadId;
  };

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>
        🗺 交通态势
      </h2>
      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 12px' }}>
        模拟交通环境 · 路网可视化 · 事件注入 · 态势感知
      </p>

      {error && (
        <div style={{
          background: '#FEF2F2', border: '1px solid #FECACA',
          borderRadius: 8, padding: '8px 12px', marginBottom: 12,
          fontSize: 12, color: '#DC2626',
        }}>
          {error}
          <button onClick={() => setError(null)} style={{
            marginLeft: 8, background: 'none', border: 'none',
            color: '#DC2626', cursor: 'pointer', fontSize: 12, fontWeight: 600,
          }}>✕</button>
        </div>
      )}

      {/* Main layout */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* Left: Control Panel */}
        <SimulationControlPanel
          scenarios={scenarios}
          selectedScenarioId={selectedScenarioId}
          onSelectScenario={setSelectedScenarioId}
          onCreateSimulation={handleCreateSimulation}
          onInjectEvent={handleInjectEvent}
          onReset={handleReset}
          run={run}
          events={events}
          loading={loading}
        />

        {/* Right: Map + Detail */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <TrafficMapView
            networkGeoJSON={networkGeoJSON}
            snapshot={snapshot}
            onRoadClick={handleRoadClick}
            onCameraClick={handleCameraClick}
            mapHeight={480}
          />

          {/* Bottom panels */}
          <div style={{ display: 'grid', gridTemplateColumns: selectedRoad || selectedCameraId ? '1fr 1fr' : '1fr', gap: 10 }}>
            {/* Status bar */}
            <div style={{
              background: '#FFF', borderRadius: 10, border: '1px solid #E5E7EB',
              padding: '10px 14px', fontSize: 11, color: '#6B7280',
              display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
            }}>
              {run ? (
                <>
                  <span>Run: <code style={{ fontSize: 10 }}>{run.runId.slice(0, 18)}...</code></span>
                  <span>Snapshots: <strong>{run.snapshotCount}</strong></span>
                  <span>Events: <strong>{events.length}</strong></span>
                  <span>Status: <span style={{
                    color: run.status === 'running' ? '#0F766E' : '#6B7280',
                    fontWeight: 600,
                  }}>{run.status}</span></span>
                </>
              ) : (
                <span>尚未创建仿真 — 请先选择场景并点击「创建仿真」</span>
              )}
              <span style={{
                marginLeft: 'auto', color: '#EF4444', fontWeight: 700, fontSize: 10,
              }}>SIMULATED</span>
            </div>

            {/* Road detail */}
            {selectedRoad && (
              <div style={{
                background: '#FFF', borderRadius: 10, border: '1px solid #E5E7EB',
                padding: '10px 14px', fontSize: 12,
              }}>
                <div style={{ fontWeight: 700, color: '#111827', marginBottom: 6 }}>
                  🛣 {getRoadName(selectedRoad.roadId)}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 12px', color: '#374151' }}>
                  <span>速度: <strong>{selectedRoad.state.avgSpeed} km/h</strong></span>
                  <span>排队: <strong>{selectedRoad.state.queueLength} m</strong></span>
                  <span>占有率: <strong>{(selectedRoad.state.occupancy * 100).toFixed(0)}%</strong></span>
                  <span>流量: <strong>{selectedRoad.state.flow} veh/h</strong></span>
                  <span>通行能力: <strong>{selectedRoad.state.effectiveCapacity} veh/h</strong></span>
                  <span>拥堵: <strong style={{
                    color: selectedRoad.state.congestionLevel === 'severe' ? '#EF4444' :
                           selectedRoad.state.congestionLevel === 'congested' ? '#F97316' :
                           selectedRoad.state.congestionLevel === 'slow' ? '#F59E0B' : '#22C55E',
                  }}>{selectedRoad.state.congestionLevel}</strong></span>
                </div>
              </div>
            )}

            {/* Camera detail */}
            {selectedCameraId && (
              <div style={{
                background: '#FFF', borderRadius: 10, border: '1px solid #E5E7EB',
                padding: '10px 14px', fontSize: 12,
              }}>
                <div style={{ fontWeight: 700, color: '#111827', marginBottom: 6 }}>
                  📷 {selectedCameraId}
                </div>
                <div style={{ fontSize: 10, color: '#EF4444', fontWeight: 600, marginBottom: 4 }}>
                  SIMULATED CAMERA
                </div>
                <div style={{ color: '#6B7280', fontSize: 11 }}>
                  点击摄像头查看模拟观测数据。
                  Phase 13 V1: 摄像头为路网固定传感器，返回所在路段交通状态。
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
