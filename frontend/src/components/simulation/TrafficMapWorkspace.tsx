/**
 * TrafficMapWorkspace — Phase 13 Frontend Closure
 *
 * Layout: Toolbar | Map (65-75%) | Context Panel (340px)
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { TrafficMapView } from './TrafficMapView';
import { TrafficMapToolbar } from './TrafficMapToolbar';
import { TrafficContextPanel } from './TrafficContextPanel';
import { RealEventsPanel } from './RealEventsPanel';
import {
  listScenarios, createSimulation, getSimulation, getNetwork, getSnapshot,
  injectEvent, resetSimulation,
} from '../../api/simulationApi';
import { processApproval } from '../../api/workflowApi';
import type {
  SimulationScenario, SimulationRun, TrafficSnapshot, TrafficEvent, TrafficRoadState,
} from '../../types/simulation';
import { visualTokens } from '../../styles/visualTokens';

const { color, radius, shadow } = visualTokens;

interface Props {
  workflowRunId: string | null;
  onWorkflowRunIdChange: (runId: string | null) => void;
  onOpenWorkflowRun: (runId: string) => void;
  focusEventId: string | null;
  focusRoadName: string | null;
  focusRisk: string | null;
  onClearFocus: () => void;
  onOpenRoad?: (roadName: string) => void;
  onOpenPlan?: (planId: string) => void;
  onOpenCollaboration?: (sessionId: string) => void;
  onOpenKnowledge?: () => void;
}

type TrafficMode = 'realtime' | 'simulation';

export const TrafficMapWorkspace: React.FC<Props> = ({
  workflowRunId: appWfRunId, onWorkflowRunIdChange, onOpenWorkflowRun,
  focusEventId, focusRoadName, focusRisk, onClearFocus, onOpenRoad, onOpenPlan, onOpenCollaboration, onOpenKnowledge,
}) => {
  const [scenarios, setScenarios] = useState<SimulationScenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('scenario_c_accident');
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [networkGeoJSON, setNetworkGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [snapshot, setSnapshot] = useState<TrafficSnapshot | null>(null);
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRoad, setSelectedRoad] = useState<{ roadId: string; roadName?: string; state: TrafficRoadState } | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [wfRunId, setWfRunId] = useState<string | null>(appWfRunId);
  const [wfStatus, setWfStatus] = useState<string | null>(null);
  const [beforeSnapshot, setBeforeSnapshot] = useState<TrafficSnapshot | null>(null);
  const [trafficMode, setTrafficMode] = useState<TrafficMode>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('simulationRunId') ? 'simulation' : 'realtime';
  });
  const runIdRef = useRef('');

  // Sync app workflowRunId
  useEffect(() => { if (appWfRunId && appWfRunId !== wfRunId) setWfRunId(appWfRunId); }, [appWfRunId]);

  // Load scenarios + URL restore
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlRunId = params.get('simulationRunId');
    if (urlRunId && !runIdRef.current) {
      setTrafficMode('simulation');
      listScenarios().then(res => { setScenarios(res.scenarios); if (res.scenarios.length > 0) setSelectedScenarioId(res.scenarios[0].scenarioId); }).catch(() => {});
      restoreSimulation(urlRunId);
    }
  }, []);

  const updateUrl = useCallback((runId?: string, wfId?: string | null) => {
    const url = new URL(window.location.href);
    if (runId) url.searchParams.set('simulationRunId', runId);
    if (wfId) url.searchParams.set('workflowRunId', wfId);
    else if (wfId === null) url.searchParams.delete('workflowRunId');
    window.history.replaceState({}, '', url.toString());
  }, []);

  const restoreSimulation = async (runId: string) => {
    try { setLoading(true); const [detail, network] = await Promise.all([getSimulation(runId), getNetwork(runId)]); setNetworkGeoJSON(network); if (detail.snapshot) setSnapshot(detail.snapshot as TrafficSnapshot); setRun(detail.run as unknown as SimulationRun); setEvents((detail.events || []) as unknown as TrafficEvent[]); runIdRef.current = runId; updateUrl(runId); } catch (err) { setError(`恢复失败: ${err instanceof Error ? err.message : String(err)}`); } finally { setLoading(false); }
  };

  // ── Actions ──────────────────────────────────────────────────
  const handleCreate = async () => { setError(null); setLoading(true); try { const res = await createSimulation(selectedScenarioId); setNetworkGeoJSON(res.network); setSnapshot(res.snapshot); setRun(res.run); setEvents([]); setWfRunId(null); onWorkflowRunIdChange(null); setWfStatus(null); setSelectedRoad(null); setSelectedCameraId(null); updateUrl(res.run.runId, null); runIdRef.current = res.run.runId; } catch (err) { setError(`创建失败: ${err instanceof Error ? err.message : String(err)}`); } finally { setLoading(false); } };

  const handleNewSim = () => { setRun(null); setNetworkGeoJSON(null); setSnapshot(null); setEvents([]); setWfRunId(null); onWorkflowRunIdChange(null); setWfStatus(null); setSelectedRoad(null); setSelectedCameraId(null); runIdRef.current = ''; updateUrl(); setLoading(false); setError(null); };

  const handleInject = async () => { if (!run) return; setError(null); setLoading(true); try { const scenario = scenarios.find(s => s.scenarioId === selectedScenarioId); const ed = scenario?.initialEvents?.[0]; const res = await injectEvent(run.runId, { eventType: (ed?.event_type as string) || 'accident', severity: (ed?.severity as string) || 'high', roadId: (ed?.road_id as string) || 'R01', longitude: (ed?.longitude as number) || 116.397, latitude: (ed?.latitude as number) || 39.907, description: (ed?.description as string) || '模拟交通事故' }); setSnapshot(res.snapshot); setEvents(prev => [...prev, res.event]); const detail = await getSimulation(run.runId); setRun(detail.run as unknown as SimulationRun); } catch (err) { setError(`事件注入失败: ${err instanceof Error ? err.message : String(err)}`); } finally { setLoading(false); } };

  const handleReset = async () => { if (!run) return; setError(null); setLoading(true); try { await resetSimulation(run.runId); const detail = await getSimulation(run.runId); setRun(detail.run as unknown as SimulationRun); setSnapshot(detail.snapshot as TrafficSnapshot); setEvents((detail.events || []) as unknown as TrafficEvent[]); setSelectedRoad(null); setSelectedCameraId(null); } catch (err) { setError(`重置失败: ${err instanceof Error ? err.message : String(err)}`); } finally { setLoading(false); } };

  const handleStartWorkflow = async () => { if (!run || events.length === 0) return; setError(null); setLoading(true); try { const activeEvent = events.find(e => e.status === 'active'); const eventId = activeEvent?.eventId; if (!eventId) { setError('没有活跃事件'); setLoading(false); return; } setBeforeSnapshot(snapshot); const resp = await fetch(`/api/traffic-map/simulations/${encodeURIComponent(run.runId)}/workflow`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ eventId, sessionId: '' }) }); if (!resp.ok) { const errData = await resp.json().catch(() => ({ detail: resp.statusText })); throw new Error((errData as { detail?: string }).detail || `Workflow start failed: ${resp.status}`); } const reader = resp.body?.getReader(); if (!reader) throw new Error('No body'); const decoder = new TextDecoder(); let buffer = ''; let streamDone = false; while (!streamDone) { const { done, value } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || ''; let ce = ''; for (const line of lines) { if (line.startsWith('event: ')) ce = line.slice(7).trim(); else if (line.startsWith('data: ')) { try { const d = JSON.parse(line.slice(6)); if (ce === 'workflow_started' && d.runId) { setWfRunId(d.runId); onWorkflowRunIdChange(d.runId); setWfStatus('running'); updateUrl(undefined, d.runId); } else if (ce === 'approval_required') { setWfStatus('awaiting_approval'); } else if (ce === 'workflow_completed') { setWfStatus('completed'); updateSnapshot(); } else if (ce === 'done') { streamDone = true; } } catch { /* skip */ } } } } } catch (err) { setError(`Workflow 启动失败: ${err instanceof Error ? err.message : String(err)}`); } finally { setLoading(false); } };

  const updateSnapshot = async () => { if (!run) return; try { const res = await getSnapshot(run.runId); setSnapshot(res); } catch { /* ignore */ } };

  // ── Inline Approval ──────────────────────────────────────────
  const handleApprove = async () => { if (!wfRunId || !run) return; try { const detail = await fetch(`/api/workflow/runs/${encodeURIComponent(wfRunId)}`).then(r => r.json()); const pending = (detail.state as Record<string,unknown>)?.pendingApproval as Record<string,unknown> | undefined; const approvalId = pending?.approvalId as string; if (!approvalId) { setError('找不到审批ID'); return; } await processApproval(wfRunId, approvalId, { action: 'approve', comment: '批准分流处置' }); setWfStatus('running'); const resp = await fetch(`/api/workflow/runs/${encodeURIComponent(wfRunId)}/resume`, { method: 'POST' }); const reader = resp.body?.getReader(); if (!reader) return; const decoder = new TextDecoder(); let buffer = ''; while (true) { const { done, value } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || ''; for (const line of lines) { if (line.startsWith('data: ')) { try { const d = JSON.parse(line.slice(6)); if (d.status === 'completed') { setWfStatus('completed'); updateSnapshot(); } } catch { /* skip */ } } } } } catch (err) { setError(`审批失败: ${err instanceof Error ? err.message : String(err)}`); } };

  const handleReject = async () => { if (!wfRunId) return; try { const detail = await fetch(`/api/workflow/runs/${encodeURIComponent(wfRunId)}`).then(r => r.json()); const pending = (detail.state as Record<string,unknown>)?.pendingApproval as Record<string,unknown> | undefined; const approvalId = pending?.approvalId as string; if (!approvalId) { setError('找不到审批ID'); return; } await processApproval(wfRunId, approvalId, { action: 'reject', comment: '驳回' }); setWfStatus('rejected'); } catch (err) { setError(`驳回失败: ${err instanceof Error ? err.message : String(err)}`); } };

  // F1 修复：wfRunId 缺失时不跳转（按钮 disabled，不假装跳列表成功）
  const handleViewWorkflow = () => { if (!wfRunId) return; onOpenWorkflowRun(wfRunId); };

  // ── Map callbacks ────────────────────────────────────────────
  const handleRoadClick = useCallback((roadId: string, state: TrafficRoadState, roadName?: string) => { setSelectedRoad({ roadId, roadName, state }); setSelectedCameraId(null); }, []);
  const handleCameraClick = useCallback((cameraId: string) => { setSelectedCameraId(cameraId); setSelectedRoad(null); }, []);

  const hasActiveEvents = events.some(e => e.status === 'active');
  const roadStates = snapshot?.roadStates ?? {};
  const congestionSummary = useMemo(() => {
    const counts = { normal: 0, slow: 0, congested: 0, severe: 0 };
    Object.values(roadStates).forEach(state => { counts[state.congestionLevel] += 1; });
    return counts;
  }, [roadStates]);
  const selectedRoadEventCount = selectedRoad
    ? events.filter(e => e.status === 'active' && e.roadId === selectedRoad.roadId).length
    : 0;

  return (
    <div className="traffic-workspace" style={{ width: '100%' }}>
      <style>{`
        .traffic-workbench-grid {
          display: grid;
          grid-template-columns: minmax(520px, 1fr) 340px;
          gap: 14px;
          align-items: stretch;
        }
        .traffic-summary-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 8px;
          margin-top: 12px;
        }
        .traffic-control-button {
          transition: background 160ms ease, border-color 160ms ease, color 160ms ease, transform 160ms ease;
        }
        .traffic-control-button:not(:disabled):hover {
          transform: translateY(-1px);
        }
        @media (max-width: 1180px) {
          .traffic-workbench-grid { grid-template-columns: 1fr; }
          .traffic-context-rail { max-width: none !important; }
        }
        @media (max-width: 900px) {
          .traffic-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
          .traffic-map-shell { padding: 12px !important; }
        }
        @media (max-width: 640px) {
          .traffic-summary-grid { grid-template-columns: 1fr !important; }
          .traffic-workspace { padding-bottom: 12px; }
        }
      `}</style>
      <header style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, lineHeight: 1.25, color: color.text, fontWeight: 600 }}>交通态势</h1>
            <div style={{ marginTop: 6, fontSize: 13, color: color.textMuted }}>真实事件态势 · Agent 研判 · 处置方案 · 工作流执行追踪</div>
          </div>
        </div>
      </header>

      {error && (
        <div style={{ background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: radius.md, padding: '8px 12px', marginBottom: 8, fontSize: 12, color: color.danger, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {error}
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: color.danger, cursor: 'pointer', fontSize: 14 }}>✕</button>
        </div>
      )}

      {trafficMode === 'simulation' ? (
      <section className="traffic-map-shell" style={{ background: color.surface, border: `1px solid ${color.border}`, borderRadius: radius.md, padding: 14, boxShadow: shadow.subtle }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: color.text }}>演练模式</div>
            <div style={{ marginTop: 3, fontSize: 11, color: color.textMuted }}>
              用于验证 TrafficMind 处置闭环，不代表真实道路 GIS。
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end', fontSize: 11 }}>
            <InlineChip label="严重" value={congestionSummary.severe} color="#B91C1C" />
            <InlineChip label="拥堵" value={congestionSummary.congested} color="#EA580C" />
            <InlineChip label="缓行" value={congestionSummary.slow} color="#D97706" />
          </div>
        </div>

        <TrafficMapToolbar
          scenarios={scenarios} selectedScenarioId={selectedScenarioId} onSelectScenario={setSelectedScenarioId}
          onCreateSimulation={handleCreate} onNewSimulation={handleNewSim} onInjectEvent={handleInject}
          onStartWorkflow={handleStartWorkflow} onReset={handleReset}
          run={run} hasActiveEvents={hasActiveEvents} workflowRunId={wfRunId} workflowStatus={wfStatus} loading={loading}
        />

        <div className="traffic-workbench-grid">
          <div style={{ minWidth: 0 }}>
            <TrafficMapView
              networkGeoJSON={networkGeoJSON}
              snapshot={snapshot}
              events={events}
              onRoadClick={handleRoadClick}
              onCameraClick={handleCameraClick}
              mapHeight="clamp(420px, 62vh, 560px)"
              selectedRoadId={selectedRoad?.roadId ?? null}
              isRunning={run?.status === 'running' || wfStatus === 'running'}
            />
            <div style={{ display: 'grid', gridTemplateColumns: selectedRoad || selectedCameraId ? 'repeat(auto-fit, minmax(220px, 1fr))' : '1fr', gap: 8, marginTop: 8 }}>
              {selectedRoad ? (
                <div style={{ background: color.surface, borderRadius: radius.md, border: `1px solid ${color.borderSubtle}`, padding: '10px 12px', fontSize: 12, color: color.text, boxShadow: shadow.subtle }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 8 }}>
                    <strong style={{ color: color.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 600 }}>{selectedRoad.roadName || selectedRoad.roadId}</strong>
                    <span style={{ fontSize: 11, color: color.textSubtle }}>路段编号 {selectedRoad.roadId}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(96px, 1fr))', gap: 8 }}>
                    <TelemetryMetric label="平均速度" value={`${selectedRoad.state.avgSpeed} km/h`} />
                    <TelemetryMetric label="排队长度" value={`${selectedRoad.state.queueLength} m`} />
                    <TelemetryMetric label="占有率" value={`${Math.round(selectedRoad.state.occupancy * 100)}%`} />
                    <TelemetryMetric label="活跃事件" value={selectedRoadEventCount} />
                  </div>
                  <div style={{ marginTop: 8, fontSize: 11, color: congestionColor(selectedRoad.state.congestionLevel), fontWeight: 650 }}>{congestionLabel(selectedRoad.state.congestionLevel)}</div>
                </div>
              ) : (
                <div style={{ background: color.surfaceMuted, borderRadius: radius.md, border: `1px solid ${color.borderSubtle}`, padding: '9px 12px', fontSize: 12, color: color.textMuted }}>
                  选择拓扑中的路段可查看模拟速度、排队长度、占有率和活跃事件数。
                </div>
              )}
              {selectedCameraId && (
                <div style={{ background: color.surfaceMuted, borderRadius: radius.md, border: `1px solid ${color.borderSubtle}`, padding: '9px 12px', fontSize: 12 }}>
                  <strong style={{ color: color.text, fontWeight: 600 }}>模拟摄像头</strong>
                  <span style={{ marginLeft: 8, color: color.textSubtle, fontSize: 11 }}>{selectedCameraId}</span>
                  <div style={{ color: color.textMuted, fontSize: 11, marginTop: 3 }}>模拟摄像头，仅用于当前拓扑推演。</div>
                </div>
              )}
            </div>
          </div>
          <TrafficContextPanel
            snapshot={snapshot} events={events} run={run}
            workflowRunId={wfRunId} workflowStatus={wfStatus}
            onApprove={handleApprove} onReject={handleReject} onViewWorkflow={handleViewWorkflow}
            beforeSnapshot={beforeSnapshot}
          />
        </div>
      </section>
      ) : (
        <RealEventsPanel
          focusEventId={focusEventId}
          focusRoadName={focusRoadName}
          focusRisk={focusRisk}
          onClearFocus={onClearFocus}
          onOpenRun={onOpenWorkflowRun}
          onOpenRoad={onOpenRoad}
          onOpenPlan={onOpenPlan}
          onOpenCollaboration={onOpenCollaboration}
          onOpenKnowledge={onOpenKnowledge}
        />
      )}
    </div>
  );
};

const InlineChip: React.FC<{ label: string; value: number; color: string }> = ({ label, value, color: tone }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 8px', border: `1px solid ${color.borderSubtle}`, borderRadius: radius.sm, background: color.surfaceMuted, color: color.textMuted }}>
    <span style={{ width: 7, height: 7, borderRadius: 999, background: tone }} />
    {label} <strong style={{ color: color.text, fontVariantNumeric: 'tabular-nums' }}>{value}</strong>
  </span>
);

const TelemetryMetric: React.FC<{ label: string; value: string | number }> = ({ label, value }) => (
  <div style={{ minWidth: 0 }}>
    <div style={{ fontSize: 11, color: color.textMuted }}>{label}</div>
    <div style={{ marginTop: 2, fontSize: 13, color: color.text, fontWeight: 650, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{value}</div>
  </div>
);

function congestionLabel(level: string): string {
  const labels: Record<string, string> = { normal: '正常', slow: '缓行', congested: '拥堵', severe: '严重' };
  return labels[level] ?? level;
}

function congestionColor(level: string): string {
  const colors: Record<string, string> = { normal: color.primary, slow: '#B7791F', congested: '#C05621', severe: '#B91C1C' };
  return colors[level] ?? color.textMuted;
}
