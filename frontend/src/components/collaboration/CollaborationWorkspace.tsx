import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { reduceCollaborationEvent } from '../../utils/collaborationEventReducer';
import { collabApi } from '../../api/collaborationApi';
import type { CollaborationRun, CollaborationTask, CollaborationAgentResult } from '../../types/collaboration';
import CollaborationRunView from './CollaborationRunView';
import { RelatedWorkflowRuns } from '../workflow/RelatedWorkflowRuns';

interface CollaborationWorkspaceProps {
  activeSessionId: string | null;
  onRefresh: () => void;
  onSessionCreated: (id: string) => void;
  onOpenRun: (runId: string) => void;
}

interface RunListItem {
  run_id: string;
  status: string;
  started_at?: string;
  startedAt?: string;
}

export function CollaborationWorkspace({
  activeSessionId,
  onRefresh,
  onSessionCreated,
  onOpenRun,
}: CollaborationWorkspaceProps) {
  const [activeRunId, setActiveRunId] = useState<string>('');
  const [runsById, setRunsById] = useState<Record<string, CollaborationRun>>({});
  const [runList, setRunList] = useState<RunListItem[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, unknown>[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const isSubmitting = useRef(false);
  const sessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (activeSessionId && activeSessionId !== sessionIdRef.current) {
      sessionIdRef.current = activeSessionId;
    }
  }, [activeSessionId]);

  const activeRun = activeRunId ? runsById[activeRunId] || null : null;

  const deserializeRunDetail = (detail: Record<string, unknown>, runId: string): CollaborationRun => {
    const run = (detail.run || detail) as Record<string, unknown>;
    const rawTasks = (detail.tasks || []) as Record<string, unknown>[];
    const tasks: CollaborationTask[] = rawTasks.map((t: Record<string, unknown>) => ({
      taskId: String(t.taskId ?? t.task_id ?? ''),
      agentName: String(t.agentName ?? t.agent_name ?? ''),
      taskType: String(t.taskType ?? t.task_type ?? 'analyze'),
      status: (t.status as CollaborationTask['status']) || 'succeeded',
      dependsOn: parseJson<string[]>(t.dependsOn ?? t.depends_on, []),
      priority: Number(t.priority || 5),
      attempt: Number(t.attempt || 1),
      maxRetries: Number(t.maxRetries ?? t.max_retries ?? 1),
      timeoutSeconds: Number(t.timeoutSeconds ?? t.timeout_seconds ?? 30),
      error: String(t.error ?? t.error_message ?? ''),
    }));

    const agentResults: Record<string, CollaborationAgentResult> = {};
    for (const t of rawTasks) {
      const os = parseJson<Record<string, unknown>>(t.output_snapshot ?? t.outputSnapshot, {});
      const an = String(t.agentName ?? t.agent_name ?? '');
      if (an && Object.keys(os).length > 0 && !['ConflictDetector', 'FusionAgent'].includes(an)) {
        agentResults[an] = {
          agentName: an,
          role: '',
          status: 'completed',
          findings: safeArray<string>(os.findings),
          confidence: Number(os.confidence || 0),
          suggestion: String(os.suggestion || os.recommendation || ''),
          urgency: String(os.urgency || 'low'),
          evidenceRefs: safeArray<string>(os.evidenceRefs),
          attempt: 1,
          duration: 0,
        };
      }
    }

    const fdRaw = run.final_decision ?? run.finalDecision;
    const fd: Record<string, unknown> = typeof fdRaw === 'string'
      ? parseJson(fdRaw, {})
      : (fdRaw as Record<string, unknown>) || {};
    const budgetRaw = run.budget_usage ?? run.budgetUsage;
    const budget: CollaborationRun['budgetUsage'] = typeof budgetRaw === 'string'
      ? parseJson(budgetRaw, emptyBudget())
      : (budgetRaw as CollaborationRun['budgetUsage']) || emptyBudget();
    const previousRaw = run.previous_run_context ?? run.previousRunContext ?? null;

    return {
      runId,
      traceId: String(run.trace_id ?? run.traceId ?? ''),
      sessionId: String(run.session_id ?? run.sessionId ?? ''),
      status: (run.status as CollaborationRun['status']) || 'completed',
      executionEngine: 'orchestrator',
      protocolVersion: '1.0',
      selectedAgents: parseJson<string[]>(run.selected_agents ?? run.selectedAgents, []),
      skippedAgents: parseJson<string[]>(run.skipped_agents ?? run.skippedAgents, []),
      routingReasons: parseJson<string[]>(run.routing_reasons ?? run.routingReasons, []),
      tasks,
      agentResults,
      conflicts: [],
      arbitrationResults: [],
      failedAgents: parseJson<string[]>(run.failed_agents ?? run.failedAgents, []),
      limitations: parseJson<string[]>(run.limitations, []),
      budgetUsage: budget,
      finalDecision: typeof fdRaw === 'string' ? fdRaw : fdRaw ? JSON.stringify(fdRaw) : '',
      fusionSummary: String(fd.fusionSummary || fd.fusion_summary || ''),
      requiresHumanReview: Boolean(fd.requiresHumanReview ?? fd.requires_human_review),
      degraded: Boolean(run.degraded),
      fallbackReason: String(run.fallbackReason ?? run.fallback_reason ?? ''),
      startedAt: String(run.started_at ?? run.startedAt ?? ''),
      completedAt: String(run.updated_at ?? run.updatedAt ?? ''),
      isHydrated: true,
      userQuery: String(run.userQuery ?? run.user_query ?? ''),
      contextPolicy: String(run.contextPolicy ?? run.context_policy ?? 'fresh_event'),
      fieldSources: parseJson<Record<string, string>>(run.fieldSources ?? run.field_sources, {}),
      previousRunContext: parseJson<CollaborationRun['previousRunContext']>(previousRaw, null),
    };
  };

  const hydrateRun = (runId: string) => {
    if (!runId) return;
    const existing = runsById[runId];
    if (existing?.isHydrated) return;

    collabApi.getRun(runId).then(detail => {
      const r = deserializeRunDetail(detail, runId);
      setRunsById(prev => {
        const cur = prev[runId];
        const merged: CollaborationRun = {
          ...(cur || createEmptyRun(r.sessionId)),
          ...r,
          fusionSummary: r.fusionSummary || cur?.fusionSummary || '',
          isHydrated: true,
        };
        return { ...prev, [runId]: merged };
      });
    }).catch((e: unknown) => {
      setHistoryError(e instanceof Error ? e.message : '协同运行详情加载失败');
    });
  };

  useEffect(() => {
    if (activeRunId) hydrateRun(activeRunId);
  }, [activeRunId]);

  useEffect(() => {
    let cancelled = false;
    if (!activeSessionId) {
      sessionIdRef.current = null;
      setRunsById({});
      setRunList([]);
      setActiveRunId('');
      setMessages([]);
      setHistoryError(null);
      setHistoryLoading(false);
      return;
    }

    setHistoryLoading(true);
    setHistoryError(null);
    fetch(`/api/chat/sessions/${encodeURIComponent(activeSessionId)}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setMessages(Array.isArray(d.messages) ? d.messages : []); })
      .catch(() => {});

    collabApi.listSessionRuns(activeSessionId)
      .then(items => {
        if (cancelled) return;
        const ordered = sortRunsChronologically(items);
        setRunList(ordered);
        if (ordered.length > 0) {
          const latestId = String(ordered[ordered.length - 1].run_id);
          setActiveRunId(latestId);
          hydrateRun(latestId);
        } else {
          setActiveRunId('');
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setHistoryError(e instanceof Error ? e.message : '协同运行列表加载失败');
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });

    return () => { cancelled = true; };
  }, [activeSessionId]);

  const handleAnalyze = async () => {
    if (!input.trim() || loading || isSubmitting.current) return;
    isSubmitting.current = true;
    setLoading(true);
    setStreamError(null);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const userMsg = { id: 'um_' + Date.now(), role: 'user', content: input.trim(), mode: 'collaboration', timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    const question = input.trim();
    setInput('');

    const submittedSessionId = sessionIdRef.current;
    const clientRequestId = 'req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
    const followUpPattern = /(继续|基于上|上述|刚才|同一|沿用)/;
    const explicitValuePattern = /(\d+\.?\d*)\s*(?:km\/h|公里|码|米|m|分钟|分)/;
    const contextPolicy = followUpPattern.test(question) && !explicitValuePattern.test(question)
      ? 'continue_event' : 'fresh_event';

    try {
      await collabApi.streamCollaboration(
        { sessionId: submittedSessionId, content: question, mode: 'collaboration', clientRequestId, contextPolicy },
        {
          onEvent: (event) => {
            if (event.eventType === 'session_created' && event.sessionId) {
              const sid = event.sessionId as string;
              sessionIdRef.current = sid;
              onSessionCreated(sid);
              onRefresh();
              return;
            }

            const evRunId = (event.runId as string) || '';
            if (!evRunId) return;

            const eventSid = (event.sessionId as string) || '';
            if (eventSid && eventSid !== sessionIdRef.current) {
              sessionIdRef.current = eventSid;
              onSessionCreated(eventSid);
            }

            setRunsById(prev => {
              const existing = prev[evRunId] || createEmptyRun(sessionIdRef.current || '');
              existing.runId = evRunId;
              return { ...prev, [evRunId]: reduceCollaborationEvent(existing, event) };
            });

            if (event.eventType === 'run_created') {
              setRunList(prev => {
                if (prev.some(r => r.run_id === evRunId)) return prev;
                const merged = [...prev, { run_id: evRunId, status: 'running', started_at: new Date().toISOString() }];
                return sortRunsChronologically(merged);
              });
              setActiveRunId(evRunId);
            }
            if (event.eventType === 'done' || event.eventType === 'run_completed') {
              setRunList(prev => prev.map(r => r.run_id === evRunId ? { ...r, status: 'completed' } : r));
              onRefresh();
              collabApi.getRun(evRunId).then(detail => {
                const hydrated = deserializeRunDetail(detail, evRunId);
                setRunsById(prev => {
                  const existing = prev[evRunId];
                  return {
                    ...prev,
                    [evRunId]: {
                      ...(existing || createEmptyRun(hydrated.sessionId)),
                      ...hydrated,
                      fusionSummary: hydrated.fusionSummary || existing?.fusionSummary || '',
                      isHydrated: true,
                    },
                  };
                });
              }).catch(() => {});
            }
            if (event.eventType === 'run_partial_success') {
              setRunList(prev => prev.map(r => r.run_id === evRunId ? { ...r, status: 'partial_success' } : r));
            }
            if (event.eventType === 'run_failed') {
              setRunList(prev => prev.map(r => r.run_id === evRunId ? { ...r, status: 'failed' } : r));
            }
          },
          onError: (err) => setStreamError(err || '协同分析失败'),
          signal: controller.signal,
        },
      );
    } finally {
      setLoading(false);
      isSubmitting.current = false;
    }
  };

  const handleSelectRun = (runId: string) => {
    setActiveRunId(runId);
    if (!runsById[runId]?.isHydrated) hydrateRun(runId);
  };

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <header>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>协同分析</h2>
        <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>多 Agent DAG 编排 · 冲突检测 · 融合决策</p>
      </header>

      {(historyError || streamError) && (
        <div style={errorBannerStyle}>
          <span>{historyError || streamError}</span>
          <button onClick={() => { setHistoryError(null); setStreamError(null); }} style={dismissButtonStyle}>关闭</button>
        </div>
      )}

      {runList.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {runList.map((rr, i: number) => (
            <button key={String(rr.run_id)} onClick={() => handleSelectRun(String(rr.run_id))}
              style={{
                padding: '4px 10px',
                borderRadius: 8,
                border: '1px solid #E5E7EB',
                background: activeRunId === rr.run_id ? '#F0FDFA' : '#FFF',
                color: activeRunId === rr.run_id ? '#0F766E' : '#374151',
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: activeRunId === rr.run_id ? 600 : 400,
              }}>
              第 {i + 1} 轮 · {String(rr.status || '未记录')}
            </button>
          ))}
        </div>
      )}

      <div style={inputPanelStyle}>
        <textarea value={input} onChange={e => setInput(e.target.value)}
          placeholder="输入事件描述或追问" rows={2}
          style={{ flex: '1 1 260px', minWidth: 0, border: '1px solid #E5E7EB', borderRadius: 8, padding: '8px 12px', fontSize: 13, resize: 'none', fontFamily: 'inherit', lineHeight: 1.5 }} />
        <button type="button" onClick={handleAnalyze} disabled={loading || !input.trim()}
          style={{ padding: '8px 16px', borderRadius: 8, border: 'none', background: loading || !input.trim() ? '#E5E7EB' : '#0F766E', color: '#FFF', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', fontSize: 13, whiteSpace: 'nowrap', fontWeight: 600 }}>
          {loading ? '分析中...' : '启动协同'}
        </button>
      </div>

      {messages.length > 0 && runList.length === 0 && !activeRun && (
        <div style={legacyMessagesStyle}>
          {messages.map((m: Record<string, unknown>, i: number) => (
            <div key={i} style={{ padding: '6px 0', fontSize: 12, color: '#374151', borderBottom: '1px solid #F3F4F6' }}>
              <strong>{m.role === 'user' ? '你' : 'TrafficMind'}:</strong> {String(m.content || '').slice(0, 200)}
            </div>
          ))}
        </div>
      )}

      {historyLoading && !activeRun && (
        <div style={emptyPanelStyle}>正在恢复协同运行详情...</div>
      )}

      {!historyLoading && activeSessionId && runList.length === 0 && messages.length === 0 && (
        <div style={emptyPanelStyle}>该会话暂无协同运行</div>
      )}

      {activeRun && <CollaborationRunView run={activeRun} />}

      {sessionIdRef.current && (
        <RelatedWorkflowRuns sessionId={sessionIdRef.current} onOpenRun={onOpenRun} />
      )}
    </div>
  );
}

function createEmptyRun(sessionId: string): CollaborationRun {
  return {
    runId: '',
    traceId: '',
    sessionId,
    status: 'created',
    executionEngine: 'orchestrator',
    protocolVersion: '1.0',
    selectedAgents: [],
    skippedAgents: [],
    routingReasons: [],
    tasks: [],
    agentResults: {},
    conflicts: [],
    arbitrationResults: [],
    failedAgents: [],
    limitations: [],
    budgetUsage: emptyBudget(),
    finalDecision: '',
    fusionSummary: '',
    requiresHumanReview: false,
    degraded: false,
    fallbackReason: '',
    startedAt: '',
    completedAt: '',
  };
}

function emptyBudget(): CollaborationRun['budgetUsage'] {
  return {
    maxAgents: 6,
    maxAgentCalls: 2,
    maxRetries: 2,
    maxTotalSeconds: 120,
    usedAgentCalls: {},
    usedRetries: {},
    startedAt: '',
  };
}

function sortRunsChronologically<T extends RunListItem>(runs: T[]): T[] {
  return [...runs].sort((a, b) => {
    const aTime = Date.parse(String(a.started_at ?? a.startedAt ?? ''));
    const bTime = Date.parse(String(b.started_at ?? b.startedAt ?? ''));
    if (Number.isFinite(aTime) && Number.isFinite(bTime) && aTime !== bTime) return aTime - bTime;
    return String(a.run_id).localeCompare(String(b.run_id));
  });
}

function safeArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? v as T[] : [];
}

function parseJson<T>(raw: unknown, fallback: T): T {
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) as T; } catch { return fallback; }
  }
  return (raw as T) || fallback;
}

const inputPanelStyle: CSSProperties = {
  display: 'flex',
  gap: 8,
  flexWrap: 'wrap',
  alignItems: 'stretch',
  background: '#FFF',
  border: '1px solid #E5E7EB',
  borderRadius: 8,
  padding: 10,
};

const emptyPanelStyle: CSSProperties = {
  background: '#FFF',
  borderRadius: 8,
  padding: 20,
  border: '1px solid #E5E7EB',
  textAlign: 'center',
  color: '#9CA3AF',
  fontSize: 13,
};

const legacyMessagesStyle: CSSProperties = {
  background: '#FFF',
  borderRadius: 8,
  border: '1px solid #E5E7EB',
  padding: '8px 12px',
};

const errorBannerStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 12,
  padding: '8px 12px',
  borderRadius: 8,
  border: '1px solid #FECACA',
  background: '#FEF2F2',
  color: '#DC2626',
  fontSize: 12,
};

const dismissButtonStyle: CSSProperties = {
  border: '1px solid #FECACA',
  background: '#FFF',
  color: '#DC2626',
  borderRadius: 6,
  padding: '2px 8px',
  cursor: 'pointer',
  fontSize: 11,
};
