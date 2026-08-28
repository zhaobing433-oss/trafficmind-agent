/**
 * WorkflowWorkspace — Workflow Center V2 Round 2
 *
 * A. Center (无 workflowRunId):
 *    Tab [运行记录] [工作流模板]，默认 history
 * B. Running (有 workflowRunId):
 *    复用现有 WorkflowTracePanel + SSE 实时更新
 *
 * URL contract:
 *   ?view=workflow                       → center, 默认 history
 *   ?view=workflow&workflowTab=templates  → center, templates
 *   ?view=workflow&workflowRunId=<id>     → running
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { listDefinitions, startRun, getRun, resumeRun, cancelRun, retryNode, processApproval, getRunStream } from '../../api/workflowApi';
import { WorkflowTracePanel } from './WorkflowTracePanel';
import { WorkflowErrorBoundary } from './WorkflowErrorBoundary';
import { WorkflowRunHistory } from './WorkflowRunHistory';
import { DecisionChainPanel } from './DecisionChainPanel';
import type { WorkflowDefinition } from '../../api/workflowApi';

const POLL_INTERVAL_MS = 3000;
const POLLABLE = new Set(['pending', 'running', 'paused']);

// 事件类型选项（与后端 EVENT_TYPE_MAP 一致）
const EVENT_TYPE_LABELS: Record<string, string> = {
  congestion: '拥堵', accident: '事故', illegal_parking: '违停', wrong_way: '逆行',
  pedestrian_intrusion: '行人闯入', signal_fault: '信号灯异常', vehicle_stopped: '车辆滞留', construction_block: '施工占道',
};

interface Props {
  workflowRunId: string | null;
  sessionId: string | null;
  onRunIdChange: (runId: string | null) => void;
  onOpenRun?: (runId: string) => void;
  onOpenPlan?: (planId: string) => void;
}

type PageState = 'center' | 'running';
type WorkflowTab = 'history' | 'templates';

export const WorkflowWorkspace: React.FC<Props> = ({ workflowRunId, sessionId, onRunIdChange, onOpenRun, onOpenPlan }) => {
  // ── Read workflowTab from URL ──
  const [workflowTab, setWorkflowTabState] = useState<WorkflowTab>(() => {
    const p = new URLSearchParams(window.location.search);
    const tab = p.get('workflowTab');
    return tab === 'templates' ? 'templates' : 'history';
  });

  const setWorkflowTab = useCallback((tab: WorkflowTab) => {
    setWorkflowTabState(tab);
    const url = new URL(window.location.href);
    url.searchParams.set('workflowTab', tab);
    url.searchParams.delete('workflowRunId');
    if (tab === 'templates') {
      url.searchParams.delete('workflowStatus');
      url.searchParams.delete('workflowPage');
    }
    window.history.replaceState({}, '', url.toString());
  }, []);

  const [pageState, setPageState] = useState<PageState>(
    workflowRunId ? 'running' : 'center'
  );
  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([]);
  const [loadingDefs, setLoadingDefs] = useState(true);
  const [selectedDefId, setSelectedDefId] = useState<string | null>(null);
  // 场景参数：metrics 由用户显式输入（模板 validate_event 要求 avgSpeed/queueLength/duration），
  // 不再从 severity 下拉合成固定值（真实性优先，Phase 20 R1 MUST）
  const [formValues, setFormValues] = useState({ roadName: '', eventType: 'congestion', avgSpeed: '', queueLength: '', duration: '' });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>('pending');
  const [traceRefreshKey, setTraceRefreshKey] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Polling ──
  const startPolling = useCallback((runId: string) => {
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      try {
        const detail = await getRun(runId);
        const serverStatus = (detail.run as Record<string, unknown>).status as string;
        setRunStatus(prev => {
          if (serverStatus !== prev) setTraceRefreshKey(k => k + 1);
          return serverStatus;
        });
        if (!POLLABLE.has(serverStatus)) stopPolling();
      } catch { /* retry on next interval */ }
    }, POLL_INTERVAL_MS);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const maybeStartPolling = useCallback((runId: string, status: string) => {
    if (POLLABLE.has(status)) startPolling(runId); else stopPolling();
  }, [startPolling, stopPolling]);

  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort();
    stopPolling();
  }, [stopPolling]);

  // Sync pageState when workflowRunId changes
  useEffect(() => {
    if (workflowRunId) {
      setPageState('running');
      connectLiveStream(workflowRunId);
    } else {
      setPageState('center');
      stopPolling();
    }
  }, [workflowRunId]);

  // Load definitions on mount
  useEffect(() => {
    listDefinitions('active')
      .then(d => { setDefinitions(d.definitions); setLoadingDefs(false); })
      .catch(() => { setError('Failed to load workflow definitions'); setLoadingDefs(false); });
  }, []);

  // ── SSE ──
  const connectLiveStream = useCallback((runId: string) => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController(); abortRef.current = controller;
    getRunStream(runId, {
      onEvent: (_eventType, data) => {
        setTraceRefreshKey(k => k + 1);
        const status = data.status as string | undefined;
        if (status) setRunStatus(status);
      },
      onDone: (status) => { maybeStartPolling(runId, status); },
    }, controller.signal).catch(() => {});
    return controller;
  }, [maybeStartPolling]);

  const streamResume = useCallback((runId: string) => {
    if (abortRef.current) abortRef.current.abort();
    stopPolling();
    const controller = new AbortController(); abortRef.current = controller;
    resumeRun(runId, {
      onEvent: (eventType, data) => {
        const status = (data.status as string) || eventType.replace('workflow_', '');
        setRunStatus(status); setTraceRefreshKey(k => k + 1);
      },
      onError: (msg) => { setError(msg); },
      onDone: (status) => { setTraceRefreshKey(k => k + 1); maybeStartPolling(runId, status); },
    }, controller.signal).catch((err: unknown) => {
      if (err instanceof Error && err.name !== 'AbortError') setError(err.message);
    });
  }, [maybeStartPolling, stopPolling]);

  // ── Template handlers (unchanged) ──
  const handleSelectTemplate = useCallback((defId: string) => {
    setSelectedDefId(defId); setError(null);
  }, []);

  const handleCreateRun = useCallback(async () => {
    if (!selectedDefId) return;
    // 场景参数校验：三个 metrics 是模板 validate_event 的必填项，缺失/非法时明确报错，不合成默认值
    const avgSpeed = Number(formValues.avgSpeed);
    const queueLength = Number(formValues.queueLength);
    const duration = Number(formValues.duration);
    if (formValues.avgSpeed === '' || formValues.queueLength === '' || formValues.duration === ''
        || !Number.isFinite(avgSpeed) || !Number.isFinite(queueLength) || !Number.isFinite(duration)
        || avgSpeed < 0 || queueLength < 0 || duration < 0) {
      setError('请填写有效的场景参数：平均速度 / 排队长度 / 持续时长（均为非负数值）');
      return;
    }
    setCreating(true); setError(null);
    stopPolling();
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController(); abortRef.current = controller;
    // 仅发送用户显式输入的字段；weather/timePeriod/isMainRoad 等由 validate_event 节点默认值兜底
    const event: Record<string, unknown> = {
      eventType: formValues.eventType || 'congestion',
      roadName: formValues.roadName.trim() || '未命名路段',
      avgSpeed,
      queueLength,
      duration,
    };
    try {
      await startRun(
        { definitionId: selectedDefId, sessionId: sessionId || undefined, event },
        {
          onEvent: (eventType, data) => {
            if (eventType === 'workflow_started') {
              onRunIdChange(data.runId as string);
              setPageState('running');
            }
            const status = (data.status as string) || eventType.replace('workflow_', '');
            if (status && status !== 'started') setRunStatus(status);
            if (eventType !== 'node_started') setTraceRefreshKey(k => k + 1);
            if (eventType === 'error') setError(data.message as string || 'Unknown error');
          },
          onError: (msg) => { setError(msg); setCreating(false); },
          onDone: (status) => {
            setCreating(false);
            if (workflowRunId) maybeStartPolling(workflowRunId, status || runStatus);
          },
        },
        controller.signal,
      );
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') setError(err.message);
      setCreating(false);
    }
  }, [selectedDefId, formValues, sessionId, onRunIdChange, stopPolling, maybeStartPolling, runStatus, workflowRunId]);

  // ── Approval / Cancel / Retry (unchanged) ──
  const handleApprove = useCallback(async (approvalId: string, comment: string) => {
    if (!workflowRunId) return;
    await processApproval(workflowRunId, approvalId, { action: 'approve', comment });
    streamResume(workflowRunId);
  }, [workflowRunId, streamResume]);

  const handleReject = useCallback(async (approvalId: string, comment: string) => {
    if (!workflowRunId) return;
    await processApproval(workflowRunId, approvalId, { action: 'reject', comment });
    setRunStatus('rejected'); stopPolling(); setTraceRefreshKey(k => k + 1);
  }, [workflowRunId, stopPolling]);

  const handleEditAndApprove = useCallback(async (approvalId: string, editedActions: Array<Record<string, unknown>>, comment: string) => {
    if (!workflowRunId) return;
    await processApproval(workflowRunId, approvalId, { action: 'edit_and_approve', editedActions, comment });
    streamResume(workflowRunId);
  }, [workflowRunId, streamResume]);

  const handleCancel = useCallback(async () => {
    if (!workflowRunId) return;
    stopPolling();
    try {
      await cancelRun(workflowRunId);
      setRunStatus('cancelled'); setTraceRefreshKey(k => k + 1);
    } catch (e: unknown) {
      try {
        const detail = await getRun(workflowRunId);
        setRunStatus((detail.run as Record<string,unknown>).status as string);
        setTraceRefreshKey(k => k + 1);
      } catch { setError(e instanceof Error ? e.message : 'Cancel failed'); }
    }
  }, [workflowRunId, stopPolling]);

  const handleRetry = useCallback(async (nodeId: string) => {
    if (!workflowRunId) return;
    try { await retryNode(workflowRunId, nodeId); setTraceRefreshKey(k => k + 1); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : 'Retry failed'); }
  }, [workflowRunId]);

  // Back from running → center
  const handleBackToCenter = useCallback(() => {
    onRunIdChange(null);
    setSelectedDefId(null);
    setRunStatus('pending');
    setPageState('center');
    if (abortRef.current) abortRef.current.abort();
    stopPolling();
    // Preserve current tab in URL
  }, [onRunIdChange, stopPolling]);

  // Navigate from history to run detail
  const handleSelectRun = useCallback((runId: string) => {
    onRunIdChange(runId);
  }, [onRunIdChange]);

  const TERMINAL = new Set(['completed', 'failed', 'rejected', 'cancelled']);
  const isTerminal = TERMINAL.has(runStatus);

  // ═══════════════════════════════════════════════════════════════════════════
  // Render: Workflow Center (Tabbed)
  // ═══════════════════════════════════════════════════════════════════════════
  if (pageState === 'center') {
    return (
      <WorkflowErrorBoundary>
        <div style={{ padding: '24px 32px', maxWidth: 900, margin: '0 auto' }}>
          {/* Header */}
          <div style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: '#111827', margin: 0 }}>工作流中心</h2>
            <p style={{ fontSize: 13, color: '#6B7280', marginTop: 4 }}>
              查看运行记录、跟踪执行状态或从模板启动新的工作流
            </p>
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 0, marginBottom: 20, borderBottom: '2px solid #E5E7EB' }}>
            {([
              ['history', '运行记录'],
              ['templates', '工作流模板'],
            ] as [WorkflowTab, string][]).map(([key, label]) => (
              <button key={key} onClick={() => setWorkflowTab(key)}
                style={{
                  padding: '8px 20px',
                  fontSize: 13,
                  fontWeight: workflowTab === key ? 600 : 400,
                  color: workflowTab === key ? '#0F766E' : '#6B7280',
                  background: 'none',
                  border: 'none',
                  borderBottom: workflowTab === key ? '2px solid #0F766E' : '2px solid transparent',
                  marginBottom: -2,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}>
                {label}
              </button>
            ))}
          </div>

          {/* Error banner */}
          {error && (
            <div style={{ padding: '8px 12px', borderRadius: 6, background: '#FEF2F2', color: '#DC2626', fontSize: 12, marginBottom: 16 }}>
              {error}
              <button onClick={() => setError(null)} style={{ marginLeft: 12, background: 'none', border: 'none', color: '#DC2626', cursor: 'pointer', fontSize: 12 }}>✕</button>
            </div>
          )}

          {/* ── History Tab ── */}
          {workflowTab === 'history' && (
            <WorkflowRunHistory
              onSelectRun={handleSelectRun}
              onSwitchToTemplates={() => setWorkflowTab('templates')}
            />
          )}

          {/* ── Templates Tab ── */}
          {workflowTab === 'templates' && (
            <>
              <p style={{ fontSize: 12, color: '#9CA3AF', marginTop: 0, marginBottom: 12 }}>
                选择工作流模板并启动新的处置流程
              </p>
              {loadingDefs ? (
                <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 40 }}>加载工作流模板...</div>
              ) : definitions.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 40 }}>暂无可用工作流模板</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {definitions.map(def => {
                    const nodeCount = Array.isArray(def.nodes) ? def.nodes.length : 0;
                    const isSelected = selectedDefId === def.id;
                    return (
                      <div key={def.id} onClick={() => handleSelectTemplate(def.id)}
                        style={{
                          padding: '16px 20px', borderRadius: 10, cursor: 'pointer',
                          border: `1.5px solid ${isSelected ? '#0F766E' : '#E5E7EB'}`,
                          background: isSelected ? '#F0FDFA' : '#FFFFFF', transition: 'all 0.15s',
                        }}>
                        <div>
                          <div style={{ fontSize: 15, fontWeight: 600, color: '#111827' }}>{def.name}</div>
                          <div style={{ fontSize: 12, color: '#6B7280', marginTop: 4, lineHeight: 1.5 }}>{def.description}</div>
                          <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11, color: '#9CA3AF' }}>
                            <span>ID: {def.id.slice(0, 12)}...</span>
                            <span>节点: {nodeCount}</span>
                            <span>分类: {def.category || '未分类'}</span>
                          </div>
                        </div>
                        {isSelected && (
                          <div style={{ marginTop: 16, padding: '14px 16px', borderRadius: 8, background: '#F9FAFB', border: '1px solid #E5E7EB' }}
                            onClick={e => e.stopPropagation()}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 10 }}>创建流程运行</div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                              <input placeholder="路段名称（如 G50沪渝高速匝道）" value={formValues.roadName}
                                onChange={e => setFormValues(v => ({ ...v, roadName: e.target.value }))}
                                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none' }} />
                              <select value={formValues.eventType}
                                onChange={e => setFormValues(v => ({ ...v, eventType: e.target.value }))}
                                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none', background: '#FFF' }}>
                                {Object.entries(EVENT_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                              </select>
                              <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>场景参数（输入值，非实时观测）</div>
                              <input placeholder="平均速度 avgSpeed（km/h）" inputMode="decimal" value={formValues.avgSpeed}
                                onChange={e => setFormValues(v => ({ ...v, avgSpeed: e.target.value }))}
                                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none' }} />
                              <input placeholder="排队长度 queueLength（米）" inputMode="decimal" value={formValues.queueLength}
                                onChange={e => setFormValues(v => ({ ...v, queueLength: e.target.value }))}
                                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none' }} />
                              <input placeholder="持续时长 duration（秒）" inputMode="decimal" value={formValues.duration}
                                onChange={e => setFormValues(v => ({ ...v, duration: e.target.value }))}
                                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none' }} />
                              <button onClick={handleCreateRun} disabled={creating || !formValues.roadName.trim()}
                                style={{
                                  marginTop: 4, padding: '8px 0', borderRadius: 8, border: 'none',
                                  cursor: creating ? 'not-allowed' : 'pointer',
                                  background: formValues.roadName.trim() ? 'linear-gradient(135deg, #0F766E, #14B8A6)' : '#D1D5DB',
                                  color: '#FFF', fontWeight: 600, fontSize: 13, opacity: creating ? 0.7 : 1,
                                }}>
                                {creating ? '启动中...' : '启动流程'}
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </WorkflowErrorBoundary>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Render: Run Execution (unchanged from Phase 12)
  // ═══════════════════════════════════════════════════════════════════════════
  return (
    <WorkflowErrorBoundary>
      <div style={{ padding: '16px 24px', maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button onClick={handleBackToCenter}
              style={{ background: 'none', border: '1px solid #E5E7EB', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 12, color: '#6B7280' }}>
              ← 工作流中心
            </button>
            <span style={{ fontSize: 14, fontWeight: 600, color: '#111827' }}>工作流运行</span>
            {workflowRunId && <code style={{ fontSize: 11, color: '#9CA3AF' }}>{workflowRunId}</code>}
            {!isTerminal && pollTimerRef.current && (
              <span style={{ fontSize: 10, color: '#9CA3AF' }}>⟳ 自动检测状态变化</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {!isTerminal && (
              <button onClick={handleCancel}
                style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid #FCA5A5', background: '#FFF', color: '#DC2626', cursor: 'pointer', fontSize: 12 }}>
                取消
              </button>
            )}
          </div>
        </div>

        {error && (
          <div style={{ padding: '8px 12px', borderRadius: 6, background: '#FEF2F2', color: '#DC2626', fontSize: 12, marginBottom: 12 }}>
            {error} <button onClick={() => setError(null)} style={{ marginLeft: 12, background: 'none', border: 'none', color: '#DC2626', cursor: 'pointer', fontSize: 12 }}>✕</button>
          </div>
        )}

        <div style={{ padding: '8px 14px', borderRadius: 8, marginBottom: 12, fontSize: 13,
          background: runStatus === 'completed' ? '#F0FDF4' : runStatus === 'failed' ? '#FEF2F2' :
            runStatus === 'rejected' ? '#FFF7ED' : runStatus === 'cancelled' ? '#F9FAFB' :
            runStatus === 'awaiting_approval' ? '#F5F3FF' : runStatus === 'paused' ? '#FFFBEB' : '#EFF6FF',
          border: `1px solid ${
            runStatus === 'completed' ? '#BBF7D0' : runStatus === 'failed' ? '#FECACA' :
            runStatus === 'rejected' ? '#FED7AA' : runStatus === 'cancelled' ? '#E5E7EB' :
            runStatus === 'awaiting_approval' ? '#DDD6FE' : runStatus === 'paused' ? '#FDE68A' : '#BFDBFE'
          }`,
          color: runStatus === 'completed' ? '#166534' : runStatus === 'failed' ? '#991B1B' :
            runStatus === 'rejected' ? '#9A3412' : runStatus === 'cancelled' ? '#6B7280' :
            runStatus === 'awaiting_approval' ? '#5B21B6' : runStatus === 'paused' ? '#92400E' : '#1E40AF'
        }}>
          {runStatus === 'completed' && '✅ 流程已完成'}
          {runStatus === 'failed' && '❌ 流程执行失败'}
          {runStatus === 'rejected' && '🚫 人工审批已拒绝'}
          {runStatus === 'cancelled' && '⏹ 流程已取消'}
          {runStatus === 'awaiting_approval' && '⏳ 等待人工审批'}
          {runStatus === 'running' && '▶ 流程运行中'}
          {runStatus === 'paused' && '⏸ 流程已暂停（后台等待恢复）'}
          {runStatus === 'pending' && '🕐 准备开始'}
        </div>

        {workflowRunId && (
          <WorkflowTracePanel
            key={`${workflowRunId}-${traceRefreshKey}`}
            runId={workflowRunId}
            visible={true}
            onRefresh={() => setTraceRefreshKey(k => k + 1)}
          />
        )}

        {/* Phase20 R2：决策链（只消费 decisionProvenance 安全投影）+ Run→Plan */}
        {workflowRunId && (
          <DecisionChainPanel
            key={`decision-${workflowRunId}`}
            runId={workflowRunId}
            onOpenChildRun={onOpenRun}
            onOpenPlan={onOpenPlan}
          />
        )}
      </div>
    </WorkflowErrorBoundary>
  );
};
