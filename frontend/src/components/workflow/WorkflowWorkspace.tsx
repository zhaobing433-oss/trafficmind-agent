/**
 * WorkflowWorkspace — Phase 12 Workflow V1 主页面
 *
 * A. 未选中 Run：显示模板列表 + 创建 Run 表单
 * B. 已选中 Run：显示 WorkflowTracePanel + SSE 实时更新
 *
 * 状态同步策略：
 *   - SSE 连接期间：SSE 事件推进状态
 *   - SSE done/关闭后，若 run 为非 terminal（paused/waiting）：
 *     启动低频轮询 (3s) 检测 Scheduler 后台恢复
 *   - terminal 后停止轮询
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { listDefinitions, startRun, getRun, resumeRun, cancelRun, retryNode, processApproval, getRunStream } from '../../api/workflowApi';
import { WorkflowTracePanel } from './WorkflowTracePanel';
import { WorkflowErrorBoundary } from './WorkflowErrorBoundary';
import type { WorkflowDefinition } from '../../api/workflowApi';

const POLL_INTERVAL_MS = 3000;
// Only poll for states where server-side state change is expected:
// pending (initial), running (in progress), paused (time_delay waiting for scheduler)
// awaiting_approval is excluded — it waits for user action, not a timer
const POLLABLE = new Set(['pending', 'running', 'paused']);

interface Props {
  workflowRunId: string | null;
  sessionId: string | null;
  onRunIdChange: (runId: string | null) => void;
}

type PageState = 'selecting' | 'running';

export const WorkflowWorkspace: React.FC<Props> = ({ workflowRunId, sessionId, onRunIdChange }) => {
  const [pageState, setPageState] = useState<PageState>(workflowRunId ? 'running' : 'selecting');
  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([]);
  const [loadingDefs, setLoadingDefs] = useState(true);
  const [selectedDefId, setSelectedDefId] = useState<string | null>(null);
  const [formValues, setFormValues] = useState({ roadName: '', description: '', severity: 'medium' });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>('pending');
  const [traceRefreshKey, setTraceRefreshKey] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Polling: detect server-side state changes when SSE is closed ────
  const startPolling = useCallback((runId: string) => {
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      try {
        const detail = await getRun(runId);
        const serverStatus = (detail.run as Record<string, unknown>).status as string;
        setRunStatus(prev => {
          // Only update if status actually changed
          if (serverStatus !== prev) {
            setTraceRefreshKey(k => k + 1);
          }
          return serverStatus;
        });
        // Stop polling once terminal
        if (!POLLABLE.has(serverStatus)) {
          stopPolling();
        }
      } catch {
        // Silently retry on next interval
      }
    }, POLL_INTERVAL_MS);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  // Start polling when SSE closes and run is non-terminal
  const maybeStartPolling = useCallback((runId: string, status: string) => {
    if (POLLABLE.has(status)) {
      startPolling(runId);
    } else {
      stopPolling();
    }
  }, [startPolling, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      stopPolling();
    };
  }, [stopPolling]);

  // Sync state when workflowRunId changes
  useEffect(() => {
    if (workflowRunId) {
      setPageState('running');
      connectLiveStream(workflowRunId);
    } else {
      setPageState('selecting');
      stopPolling();
    }
  }, [workflowRunId]);

  // Load definitions on mount
  useEffect(() => {
    listDefinitions('active')
      .then(d => { setDefinitions(d.definitions); setLoadingDefs(false); })
      .catch(() => { setError('Failed to load workflow definitions'); setLoadingDefs(false); });
  }, []);

  // ── SSE live stream connection ─────────────────────────────────────
  const connectLiveStream = useCallback((runId: string) => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    getRunStream(runId, {
      onEvent: (_eventType, data) => {
        setTraceRefreshKey(k => k + 1);
        const status = data.status as string | undefined;
        if (status) setRunStatus(status);
      },
      onDone: (status) => {
        maybeStartPolling(runId, status);
      },
    }, controller.signal).catch(() => {});

    return controller;
  }, [maybeStartPolling]);

  // ── SSE resume stream (after approve/edit) ─────────────────────────
  const streamResume = useCallback((runId: string) => {
    if (abortRef.current) abortRef.current.abort();
    stopPolling();
    const controller = new AbortController();
    abortRef.current = controller;

    resumeRun(runId, {
      onEvent: (eventType, data) => {
        const status = (data.status as string) || eventType.replace('workflow_', '');
        setRunStatus(status);
        setTraceRefreshKey(k => k + 1);
      },
      onError: (msg) => { setError(msg); },
      onDone: (status) => {
        setTraceRefreshKey(k => k + 1);
        maybeStartPolling(runId, status);
      },
    }, controller.signal).catch((err: unknown) => {
      if (err instanceof Error && err.name !== 'AbortError') {
        setError(err.message);
      }
    });
  }, [maybeStartPolling, stopPolling]);

  // Open create form
  const handleSelectTemplate = useCallback((defId: string) => {
    setSelectedDefId(defId);
    setError(null);
  }, []);

  // Create and start a run
  const handleCreateRun = useCallback(async () => {
    if (!selectedDefId) return;
    setCreating(true);
    setError(null);
    stopPolling();
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const event: Record<string, unknown> = {
      eventType: 'congestion',
      roadName: formValues.roadName || '未命名路段',
      avgSpeed: formValues.severity === 'high' ? 5 : formValues.severity === 'medium' ? 20 : 40,
      queueLength: formValues.severity === 'high' ? 300 : formValues.severity === 'medium' ? 150 : 50,
      duration: formValues.severity === 'high' ? 1200 : formValues.severity === 'medium' ? 600 : 180,
      weather: 'clear', timePeriod: 'off_peak',
      isMainRoad: true, nearbySchool: false, nearbyHospital: false,
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
            // After SSE closes, start polling if non-terminal
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

  // ── Approve handler ────────────────────────────────────────────────
  const handleApprove = useCallback(async (approvalId: string, comment: string) => {
    if (!workflowRunId) return;
    await processApproval(workflowRunId, approvalId, { action: 'approve', comment });
    streamResume(workflowRunId);
  }, [workflowRunId, streamResume]);

  // ── Reject handler ─────────────────────────────────────────────────
  const handleReject = useCallback(async (approvalId: string, comment: string) => {
    if (!workflowRunId) return;
    await processApproval(workflowRunId, approvalId, { action: 'reject', comment });
    setRunStatus('rejected');
    stopPolling();
    setTraceRefreshKey(k => k + 1);
  }, [workflowRunId, stopPolling]);

  // ── Edit-and-approve handler ──────────────────────────────────────
  const handleEditAndApprove = useCallback(async (approvalId: string, editedActions: Array<Record<string, unknown>>, comment: string) => {
    if (!workflowRunId) return;
    await processApproval(workflowRunId, approvalId, { action: 'edit_and_approve', editedActions, comment });
    streamResume(workflowRunId);
  }, [workflowRunId, streamResume]);

  // Cancel
  const handleCancel = useCallback(async () => {
    if (!workflowRunId) return;
    stopPolling();
    try {
      await cancelRun(workflowRunId);
      setRunStatus('cancelled');
      setTraceRefreshKey(k => k + 1);
    } catch (e: unknown) {
      try {
        const detail = await getRun(workflowRunId);
        const actualStatus = (detail.run as Record<string,unknown>).status as string;
        setRunStatus(actualStatus);
        setTraceRefreshKey(k => k + 1);
      } catch {
        setError(e instanceof Error ? e.message : 'Cancel failed');
      }
    }
  }, [workflowRunId, stopPolling]);

  // Retry node
  const handleRetry = useCallback(async (nodeId: string) => {
    if (!workflowRunId) return;
    try {
      await retryNode(workflowRunId, nodeId);
      setTraceRefreshKey(k => k + 1);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Retry failed');
    }
  }, [workflowRunId]);

  // Go back to template list
  const handleBackToTemplates = useCallback(() => {
    onRunIdChange(null);
    setSelectedDefId(null);
    setRunStatus('pending');
    setPageState('selecting');
    if (abortRef.current) abortRef.current.abort();
    stopPolling();
  }, [onRunIdChange, stopPolling]);

  const TERMINAL = new Set(['completed', 'failed', 'rejected', 'cancelled']);
  const isTerminal = TERMINAL.has(runStatus);

  // ── Render: Template Selection ──────────────────────────────────────
  if (pageState === 'selecting') {
    return (
      <WorkflowErrorBoundary>
        <div style={{ padding: '24px 32px', maxWidth: 900, margin: '0 auto' }}>
          <div style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: '#111827', margin: 0 }}>工作流</h2>
            <p style={{ fontSize: 13, color: '#6B7280', marginTop: 4 }}>
              基于受控流程执行交通事件研判、审批与处置
            </p>
          </div>
          {error && (
            <div style={{ padding: '8px 12px', borderRadius: 6, background: '#FEF2F2', color: '#DC2626', fontSize: 12, marginBottom: 16 }}>
              {error}
              <button onClick={() => setError(null)} style={{ marginLeft: 12, background: 'none', border: 'none', color: '#DC2626', cursor: 'pointer', fontSize: 12 }}>✕</button>
            </div>
          )}
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
                    style={{ padding: '16px 20px', borderRadius: 10, cursor: 'pointer',
                      border: `1.5px solid ${isSelected ? '#0F766E' : '#E5E7EB'}`,
                      background: isSelected ? '#F0FDFA' : '#FFFFFF', transition: 'all 0.15s' }}>
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
                          <input placeholder="拥堵描述（可选）" value={formValues.description}
                            onChange={e => setFormValues(v => ({ ...v, description: e.target.value }))}
                            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none' }} />
                          <select value={formValues.severity}
                            onChange={e => setFormValues(v => ({ ...v, severity: e.target.value }))}
                            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 13, outline: 'none', background: '#FFF' }}>
                            <option value="low">低严重度</option>
                            <option value="medium">中严重度</option>
                            <option value="high">高严重度</option>
                          </select>
                          <button onClick={handleCreateRun} disabled={creating || !formValues.roadName.trim()}
                            style={{ marginTop: 4, padding: '8px 0', borderRadius: 8, border: 'none',
                              cursor: creating ? 'not-allowed' : 'pointer',
                              background: formValues.roadName.trim() ? 'linear-gradient(135deg, #0F766E, #14B8A6)' : '#D1D5DB',
                              color: '#FFF', fontWeight: 600, fontSize: 13, opacity: creating ? 0.7 : 1 }}>
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
        </div>
      </WorkflowErrorBoundary>
    );
  }

  // ── Render: Run Execution ────────────────────────────────────────────
  return (
    <WorkflowErrorBoundary>
      <div style={{ padding: '16px 24px', maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button onClick={handleBackToTemplates}
              style={{ background: 'none', border: '1px solid #E5E7EB', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 12, color: '#6B7280' }}>
              ← 模板列表
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
      </div>
    </WorkflowErrorBoundary>
  );
};
