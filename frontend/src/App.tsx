import { useState, useCallback, useEffect, useRef } from 'react';
import LayoutShell from './components/LayoutShell';
import HomeHero from './components/HomeHero';
import ScenarioGrid from './components/ScenarioGrid';
import ChatWorkspace from './components/ChatWorkspace';
import { chatApi, type SessionItem } from './api/chatApi';
import { reduceCollaborationEvent } from './utils/collaborationEventReducer';
import { collabApi } from './api/collaborationApi';
import type { CollaborationRun, CollaborationTask, CollaborationAgentResult } from './types/collaboration';
import CollaborationRunView from './components/collaboration/CollaborationRunView';

const WORKSPACE_INFO: Record<string, { title: string; sub: string; showFullModes: boolean; defaultMode: string }> = {
  home: { title: '', sub: '', showFullModes: true, defaultMode: 'react' },
  qa: { title: '知识库', sub: 'RAG交通知识库 · 规则/预案/经验检索 · 证据问答', showFullModes: false, defaultMode: 'rag' },
  report: { title: '统计报告', sub: '日报/周报 · 高风险路口 · 事件趋势 · 管理建议', showFullModes: false, defaultMode: 'report' },
  multi: { title: '协同分析', sub: '多Agent研判 + 冲突检测 + 融合处置建议', showFullModes: false, defaultMode: 'routed' },
};

export default function App() {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [pendingCreate, setPendingCreate] = useState(true);
  const [view, setView] = useState('home');
  const [draftInput, setDraftInput] = useState('');
  const [draftMode, setDraftMode] = useState('react');
  const [recentRefresh, setRecentRefresh] = useState(0);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  // Stable key: only change when we WANT to reset the workspace (new conv / recent click)
  const [workspaceKey, setWorkspaceKey] = useState(0);

  useEffect(() => { chatApi.listSessions(30).then(setSessions).catch(() => {}); }, [recentRefresh]);
  const refreshSessions = useCallback(() => setRecentRefresh(Date.now()), []);
  // CRITICAL: session created via first send — do NOT reset the component (key stays same)
  const handleSessionCreated = useCallback((id: string) => { setActiveSessionId(id); setPendingCreate(false); setRecentRefresh(Date.now()); }, []);
  const handleNewConversation = () => { setActiveSessionId(null); setPendingCreate(true); setDraftInput(''); setView('home'); setWorkspaceKey(k => k + 1); };
  const handleScenario = (prompt: string, mode: string, targetView: string) => { setDraftInput(prompt); setDraftMode(mode); setView(targetView); setActiveSessionId(null); setPendingCreate(true); setWorkspaceKey(k => k + 1); };
  const handleNavigate = (v: string) => { setView(v); };
  const handleRecentClick = async (id: string) => {
    // Fetch session to determine its mode, then route to correct workspace
    try {
      const detail = await chatApi.getSession(id);
      const sessionMode = detail.session.mode || 'react';
      const viewMap: Record<string, string> = {
        react: 'home', routed: 'home', hybrid: 'home',
        rag: 'qa', collaboration: 'multi', report: 'report',
      };
      setView(viewMap[sessionMode] || 'home');
    } catch {
      setView('home');
    }
    setActiveSessionId(id); setPendingCreate(false); setDraftInput(''); setWorkspaceKey(k => k + 1);
  };
  const handleRenameSession = async (id: string, t: string) => { try { await fetch(`/api/chat/sessions/${id}/title`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: t }) }); refreshSessions(); } catch { /* ignore */ } };
  const info = WORKSPACE_INFO[view] || WORKSPACE_INFO.home;
  const recentItems = sessions.map(s => ({ id: s.id, title: s.title || '未命名交通分析', mode: s.mode, updatedAt: new Date(s.updated_at).getTime() }));

  return (
    <LayoutShell activeView={view} onNavigate={handleNavigate} onRecentClick={handleRecentClick} onNewConversation={handleNewConversation} onRenameSession={handleRenameSession} activeConvId={activeSessionId || undefined} recentList={recentItems}>
      <div style={{ maxWidth: 960, margin: '0 auto', width: '100%', padding: '0 24px 32px' }}>
        {view === 'alert' ? <AlertDashboard /> :
         view === 'guide' ? <GuidePage /> :
         view === 'report' ? <ReportDashboard /> :
         view === 'qa' ? <QaDashboard onRefresh={refreshSessions} /> :
         view === 'multi' ? <CollaborationWorkspace activeSessionId={activeSessionId || null} onRefresh={refreshSessions} /> : (
          <>
            <HomeHero />
            <ScenarioGrid onSelect={handleScenario} />
            <ChatWorkspace key={workspaceKey} sessionId={activeSessionId || undefined} pendingCreate={pendingCreate} draftInput={draftInput} draftMode={draftMode} onDraftConsumed={() => setDraftInput('')} defaultMode={info.defaultMode} showFullModes={info.showFullModes} onSessionCreated={handleSessionCreated} onConversationUpdate={refreshSessions} onNewConversation={handleNewConversation} view={view} />
          </>
        )}
        <div style={{ textAlign: 'center', padding: '24px 0 12px', fontSize: 11, color: '#D1D5DB' }}>TrafficMind Agent · 智慧交通事件研判与协同决策工作台</div>
      </div>
    </LayoutShell>
  );
}

// ========== Fusion Summary builder ==========

function buildFusionSummary(results: Record<string,unknown>): string {
  const agents = (results.agentResults as Record<string,unknown>[]) || [];
  const conflicts = (results.conflicts as Record<string,unknown>[]) || [];
  const dispatchPlan = results.dispatchPlan as Record<string,unknown> | null;
  const urgency = dispatchPlan?.urgency as string || '待评估';
  const allFindings: string[] = [];
  agents.forEach(a => { (a.findings as string[] || []).forEach(f => allFindings.push(f)); });

  const topRisk = allFindings.slice(0, 2).join('；') || '需专家进一步研判';
  const agentNames = agents.map(a => a.agentName || '').filter(Boolean).join('、');
  const conflictText = conflicts.length > 0
    ? `检测到 ${conflicts.length} 个建议冲突（${conflicts.map(c => c.type || '').filter(Boolean).join('、')}），已按安全优先和急救通道优先原则融合处理。`
    : '各Agent建议无明显冲突。';

  const actionItems = (dispatchPlan?.actions as string[] || []).slice(0, 4);
  const actionText = actionItems.length > 0
    ? `建议按以下顺序处置：${actionItems.map((a, i) => `${i + 1}) ${a}`).join('；')}。`
    : '请结合实时路况和现场信息制定具体处置方案。';

  return `综合 ${agentNames} 共 ${agents.length} 个 Agent 的分析，本事件核心风险为：${topRisk}。紧急度评估为「${urgency}」。${conflictText} ${actionText} 建议持续关注排队长度、平均速度和通行能力变化，动态调整管控力度。`;
}

// ========== Multi-Agent Workspace ==========

/** Agent streaming step */
type Step = { id: string; agentName: string; status: 'pending' | 'thinking' | 'done'; message: string; result?: Record<string,unknown> };
const AGENT_STEPS = ['CongestionAgent', 'SignalAgent', 'PublicSafetyAgent', 'DispatchAgent', 'ReportAgent'];

function CollaborationWorkspace({ activeSessionId, onRefresh }: { activeSessionId: string | null; onRefresh: () => void }) {
  return <CollaborationWorkspaceInner activeSessionId={activeSessionId} onRefresh={onRefresh} />;
}

function CollaborationWorkspaceInner({ activeSessionId, onRefresh }: { activeSessionId: string | null; onRefresh: () => void }) {
  // Core multi-run state
  const [activeRunId, setActiveRunId] = useState<string>('');
  const [runsById, setRunsById] = useState<Record<string, CollaborationRun>>({});
  const [runList, setRunList] = useState<{ run_id: string; status: string }[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Record<string, unknown>[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const isSubmitting = useRef(false);

  // Derived: active run
  const activeRun = activeRunId ? runsById[activeRunId] || null : null;

  // Hydrate run detail when switching to a non-hydrated run
  const hydrateRun = (runId: string) => {
    const existing = runsById[runId];
    if (!existing || existing.isHydrated) return;
    collabApi.getRun(runId).then(detail => {
      setRunsById(prev => {
        const cur = prev[runId];
        if (!cur) return prev;
        const rawTasks = (detail.tasks || []) as Record<string,unknown>[];
        const tasks = rawTasks.map((t: Record<string,unknown>) => ({
          taskId: String(t.taskId ?? t.task_id ?? ''), agentName: String(t.agentName ?? t.agent_name ?? ''),
          taskType: String(t.taskType ?? t.task_type ?? 'analyze'),
          status: (t.status as CollaborationTask['status']) || 'succeeded',
          dependsOn: (t.dependsOn ?? t.depends_on ?? []) as string[],
          priority: Number(t.priority || 5), attempt: Number(t.attempt || 1),
          maxRetries: Number(t.maxRetries ?? t.max_retries ?? 1),
          timeoutSeconds: Number(t.timeoutSeconds ?? t.timeout_seconds ?? 30),
          error: String(t.error ?? t.error_message ?? ''),
        } as CollaborationTask));
        // Extract agentResults from output_snapshot
        const agentResults: Record<string, CollaborationAgentResult> = {};
        for (const t of rawTasks) {
          const os = (t.output_snapshot || t.outputSnapshot || {}) as Record<string,unknown>;
          const an = String(t.agentName ?? t.agent_name ?? '');
          if (an && Object.keys(os).length > 0 && !['ConflictDetector','FusionAgent'].includes(an)) {
            agentResults[an] = {
              agentName: an, role: '', status: 'completed',
              findings: (os.findings || []) as string[],
              confidence: Number(os.confidence || 0),
              suggestion: (os.suggestion || '') as string,
              urgency: (os.urgency || 'low') as string,
              evidenceRefs: (os.evidenceRefs || []) as string[],
              attempt: 1, duration: 0,
            };
          }
        }
        return { ...prev, [runId]: { ...cur, tasks: tasks.length > 0 ? tasks : cur.tasks, agentResults, isHydrated: Boolean(tasks.length > 0 && Object.keys(agentResults).length > 0) } };
      });
    }).catch(() => {});
  };

  // When activeRunId changes to a non-hydrated run, hydrate it
  useEffect(() => {
    if (activeRunId) hydrateRun(activeRunId);
  }, [activeRunId]);

  // Load history if session exists (only on initial mount or session change)
  useEffect(() => {
    if (!activeSessionId) { setRunsById({}); setRunList([]); setActiveRunId(''); setMessages([]); return; }
    fetch(`/api/chat/sessions/${activeSessionId}`).then(r => r.json()).then(d => setMessages(d.messages || [])).catch(() => {});
    collabApi.listSessionRuns(activeSessionId).then(items => {
      setRunList(items);
      // If we don't have an active run, default to latest
      if (!activeRunId && items.length > 0) {
        setActiveRunId(items[items.length - 1].run_id); // last = newest
      }
    }).catch(() => {});
  }, [activeSessionId]);

  const handleAnalyze = async () => {
    if (!input.trim() || loading || isSubmitting.current) return;
    isSubmitting.current = true;
    setLoading(true);
    // Abort previous
    abortRef.current?.abort();
    const controller = new AbortController(); abortRef.current = controller;

    // Save user message to UI
    const userMsg = { id: 'um_' + Date.now(), role: 'user', content: input.trim(), mode: 'collaboration', timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    const question = input.trim(); setInput('');

    const sessionId = activeSessionId || undefined;
    let currentRun = createEmptyRun(sessionId || '');

    const clientRequestId = 'req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);

    // Do NOT create a temp run — only show runs from real SSE run_created events
    await collabApi.streamCollaboration(
      { sessionId, content: question, mode: 'collaboration', clientRequestId, eventType: 'congestion', roadName: '人民路', direction: '东向西', avgSpeed: 8.0, queueLength: 400, duration: 900, weather: 'rain', timePeriod: 'morning_peak', isMainRoad: true },
      {
        onEvent: (event) => {
          const evRunId = (event.runId as string) || '';
          if (!evRunId) return; // ignore events without runId

          // Update the specific run by runId — never a temp/global run
          setRunsById(prev => {
            const existing = prev[evRunId] || createEmptyRun(sessionId || '');
            existing.runId = evRunId;
            return { ...prev, [evRunId]: reduceCollaborationEvent(existing, event) };
          });

          if (event.eventType === 'session_created' && event.sessionId) {
            onRefresh();
          }
          if (event.eventType === 'run_created') {
            // Only add to runList if not already present (dedup by run_id)
            setRunList(prev => prev.some(r => r.run_id === evRunId) ? prev : [...prev, { run_id: evRunId, status: 'running' }]);
            setActiveRunId(evRunId);
          }
          // Update runList status on completion
          if (event.eventType === 'done' || event.eventType === 'run_completed') {
            setRunList(prev => prev.map(r => r.run_id === evRunId ? { ...r, status: 'completed' } : r));
            onRefresh();
            // Hydrate detail from backend to fill in any gaps
            collabApi.getRun(evRunId).then(detail => {
              setRunsById(prev => {
                const existing = prev[evRunId];
                if (!existing) return prev;
                const rawTasks = (detail.tasks || []) as Record<string,unknown>[];
                const tasks = rawTasks.map((t: Record<string,unknown>) => ({
                  taskId: String(t.taskId ?? t.task_id ?? ''), agentName: String(t.agentName ?? t.agent_name ?? ''),
                  taskType: String(t.taskType ?? t.task_type ?? 'analyze'),
                  status: (t.status as CollaborationTask['status']) || 'succeeded',
                  dependsOn: (t.dependsOn ?? t.depends_on ?? []) as string[],
                  priority: Number(t.priority || 5), attempt: Number(t.attempt || 1),
                  maxRetries: Number(t.maxRetries ?? t.max_retries ?? 1),
                  timeoutSeconds: Number(t.timeoutSeconds ?? t.timeout_seconds ?? 30),
                  error: String(t.error ?? t.error_message ?? ''),
                } as CollaborationTask));
                const agentResults: Record<string, CollaborationAgentResult> = {};
                for (const t of rawTasks) {
                  const os = (t.output_snapshot || t.outputSnapshot || {}) as Record<string,unknown>;
                  const an = String(t.agentName ?? t.agent_name ?? '');
                  if (an && Object.keys(os).length > 0 && !['ConflictDetector','FusionAgent'].includes(an)) {
                    agentResults[an] = {
                      agentName: an, role: '', status: 'completed',
                      findings: (os.findings || []) as string[],
                      confidence: Number(os.confidence || 0),
                      suggestion: (os.suggestion || '') as string,
                      urgency: (os.urgency || 'low') as string,
                      evidenceRefs: [], attempt: 1, duration: 0,
                    };
                  }
                }
                return { ...prev, [evRunId]: { ...existing, tasks: tasks.length > 0 ? tasks : existing.tasks, agentResults, isHydrated: Boolean(tasks.length > 0 && Object.keys(agentResults).length > 0) } };
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
        onError: () => { setActiveRunId(prev => prev); },
        signal: controller.signal,
      }
    );
    setLoading(false);
    isSubmitting.current = false;
  };

  const handleSelectRun = async (runId: string) => {
    try {
      const detail = await collabApi.getRun(runId);
      // Build CollaborationRun from audit data
      const r: CollaborationRun = {
        runId: detail.run.run_id as string, traceId: detail.run.trace_id as string,
        sessionId: detail.run.session_id as string, status: detail.run.status as CollaborationRun['status'],
        executionEngine: 'orchestrator', protocolVersion: '1.0',
        selectedAgents: parseJson(detail.run.selected_agents, []),
        skippedAgents: parseJson(detail.run.skipped_agents, []),
        routingReasons: [], tasks: (detail.tasks as []).map((t: Record<string,unknown>) => ({
          taskId: String(t.task_id || ''), agentName: String(t.agent_name || ''),
          taskType: String(t.task_type || 'analyze'), status: String(t.status || 'pending') as CollaborationTask['status'],
          dependsOn: parseJson(t.depends_on, []), priority: Number(t.priority || 5),
          attempt: Number(t.attempt || 0), maxRetries: Number(t.max_retries || 1),
          timeoutSeconds: Number(t.timeout_seconds || 30), error: String(t.error_message || ''),
        }) as CollaborationTask),
        agentResults: {}, conflicts: [], arbitrationResults: [],
        failedAgents: parseJson(detail.run.failed_agents, []),
        limitations: [], budgetUsage: parseJson(detail.run.budget_usage, { maxAgents: 6, maxAgentCalls: 2, maxRetries: 2, maxTotalSeconds: 120, usedAgentCalls: {}, usedRetries: {}, startedAt: '' }) as CollaborationRun['budgetUsage'],
        finalDecision: String(detail.run.final_decision || ''),
        fusionSummary: String(detail.run.final_decision || ''),
        requiresHumanReview: false, degraded: false, fallbackReason: '',
        startedAt: String(detail.run.started_at || ''), completedAt: String(detail.run.updated_at || ''),
      };
      setMessages([]);
      setRunsById(prev => ({ ...prev, [String(r.runId)]: r }));
      setActiveRunId(String(r.runId));
    } catch { /* fallback to chat messages */ }
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>协同分析</h2>
      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 8px' }}>多Agent DAG 编排 · 冲突检测 · 融合决策</p>

      {/* Run selector */}
      {runList.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          {runList.map((rr, i: number) => (
            <button key={String(rr.run_id)} onClick={() => setActiveRunId(String(rr.run_id))}
              style={{ padding: '4px 10px', borderRadius: 10, border: '1px solid #E5E7EB', background: activeRunId === rr.run_id ? '#F0FDFA' : '#FFF', cursor: 'pointer', fontSize: 12 }}>
              第{i + 1}轮 · {String(rr.status || '')}
            </button>
          ))}
        </div>
      )}

      {/* New analysis input */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <textarea value={input} onChange={e => setInput(e.target.value)}
          placeholder="输入事件描述或追问..." rows={2}
          style={{ flex: 1, border: '1px solid #E5E7EB', borderRadius: 12, padding: '8px 12px', fontSize: 13, resize: 'none', fontFamily: 'inherit' }} />
        <button type="button" onClick={handleAnalyze} disabled={loading || !input.trim()}
          style={{ padding: '8px 16px', borderRadius: 12, border: 'none', background: loading ? '#E5E7EB' : '#0F766E', color: '#FFF', cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13, whiteSpace: 'nowrap' }}>
          {loading ? '分析中...' : '启动协同'}
        </button>
      </div>

      {/* Chat messages */}
      {messages.length > 0 && !activeRun && (
        <div style={{ marginBottom: 12 }}>
          {messages.map((m: Record<string,unknown>, i: number) => (
            <div key={i} style={{ padding: '6px 0', fontSize: 12, color: '#374151' }}>
              <strong>{m.role === 'user' ? '你' : 'TrafficMind'}:</strong> {String(m.content || '').slice(0, 200)}
            </div>
          ))}
        </div>
      )}

      {/* Collaboration Run View */}
      {activeRun && <CollaborationRunView run={activeRun} />}
    </div>
  );
}

function createEmptyRun(sessionId: string): CollaborationRun {
  return {
    runId: '', traceId: '', sessionId, status: 'created', executionEngine: 'orchestrator',
    protocolVersion: '1.0', selectedAgents: [], skippedAgents: [], routingReasons: [],
    tasks: [], agentResults: {}, conflicts: [], arbitrationResults: [],
    failedAgents: [], limitations: [],
    budgetUsage: { maxAgents: 6, maxAgentCalls: 2, maxRetries: 2, maxTotalSeconds: 120, usedAgentCalls: {}, usedRetries: {}, startedAt: '' },
    finalDecision: '', fusionSummary: '', requiresHumanReview: false, degraded: false,
    fallbackReason: '', startedAt: '', completedAt: '',
  };
}

function parseJson<T>(raw: unknown, fallback: T): T {
  if (typeof raw === 'string') { try { return JSON.parse(raw) as T; } catch { return fallback; } }
  return (raw as T) || fallback;
}

// ========== Knowledge Base (QA) Dashboard ==========

function QaDashboard({ onRefresh }: { onRefresh: () => void }) {
  const [ragStatus] = useState<Record<string,unknown>>({});
  useEffect(() => { fetch('/api/rag/status').then(r => r.json()).catch(() => {}); }, []);
  const quickQs = ['雨天早高峰拥堵有哪些处置原则？', '信号灯异常应该优先检索哪些预案？', '学校周边拥堵需要关注哪些安全因素？', '为什么证据不足时系统会拒答？', '高风险路口如何判定？'];
  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>知识库</h2>
      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 8px' }}>RAG交通知识库 · 规则/预案/经验检索 · 证据问答</p>
      <div style={{ background: '#F0FDFA', borderRadius: 12, padding: '10px 14px', border: '1px solid #0F766E20', marginBottom: 10, fontSize: 12, color: '#374151', lineHeight: 1.7 }}>
        <strong>知识库用于：</strong>查询交通处置规则、信号异常预案、拥堵治理经验、事故处置原则、高风险路口判定依据、RAG检索策略和拒答原因。
        <br /><strong>不适用：</strong>知识库不直接代表实时路况，不负责真实派单，不用于生成具体事件闭环结果。具体事件处置请使用输入框能力「事件研判」或进入「协同分析」。
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        <button onClick={async () => { try { await fetch('/api/rag/rebuild_index', { method: 'POST' }); alert('索引重建完成'); } catch { alert('重建失败'); } }} style={{ padding: '5px 12px', borderRadius: 8, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12 }}>🔄 重建索引</button>
        <span style={{ fontSize: 11, color: '#9CA3AF', padding: '5px 0' }}>阈值: &lt;0.35拒答 | 0.35-0.55低置信度 | 0.55-0.75中 | ≥0.75高</span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        {quickQs.map(q => (
          <div key={q} onClick={() => { /* set input */ }} style={{ background: '#FFF', borderRadius: 10, padding: '6px 12px', border: '1px solid #E5E7EB', cursor: 'pointer', fontSize: 11, color: '#6B7280' }}>{q}</div>
        ))}
      </div>
      <ChatWorkspace sessionId={undefined} pendingCreate={true} defaultMode="rag" showFullModes={false} onSessionCreated={(id) => { onRefresh(); }} onConversationUpdate={onRefresh} onNewConversation={() => {}} view="qa" />
    </div>
  );
}

// ========== Report Dashboard ==========

function ReportDashboard() {
  const [stats, setStats] = useState<Record<string,unknown>>({});
  const [roads, setRoads] = useState<Record<string,unknown>[]>([]);
  const [alerts, setAlerts] = useState<Record<string,unknown>[]>([]);
  const [daily, setDaily] = useState<Record<string,unknown> | null>(null);
  useEffect(() => {
    fetch('/api/stats').then(r => r.json()).then(setStats).catch(() => {});
    fetch('/api/stats/high_risk_roads?days=30').then(r => r.json()).then(d => setRoads(d.topRoads || [])).catch(() => {});
    fetch('/api/alerts/unclosed?hours=720').then(r => r.json()).then(d => setAlerts(d.alerts || [])).catch(() => {});
    fetch('/api/reports/daily').then(r => r.json()).then(setDaily).catch(() => {});
  }, []);

  const typeDist = (stats.eventTypeDistribution as Record<string,unknown>[]) || [];
  const riskDist = (stats.riskDistribution as Record<string,unknown>[]) || [];
  const findings = (daily?.keyFindings as string[]) || [];
  const suggestions = (daily?.suggestions as string[]) || [];

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 12px' }}>统计报告</h2>
      {/* Top metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 14 }}>
        {[{ l: '总事件数', v: String(stats.totalEvents || 0), c: '#0F766E' }, { l: '高风险', v: String(stats.highRiskCount || 0), c: '#EF4444' }, { l: '待处置', v: String(stats.pendingDispatch || 0), c: '#F59E0B' }, { l: '平均风险分', v: String(stats.avgRiskScore || 0), c: '#3B82F6' }].map(x => (
          <div key={x.l} style={{ background: '#FFF', borderRadius: 14, padding: '12px 16px', border: '1px solid #E5E7EB' }}><div style={{ fontSize: 11, color: '#9CA3AF' }}>{x.l}</div><div style={{ fontSize: 24, fontWeight: 700, color: x.c }}>{x.v}</div></div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Event type distribution */}
        <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>事件类型分布</div>
          {typeDist.length === 0 ? <div style={{ fontSize: 12, color: '#9CA3AF' }}>暂无数据</div> :
            typeDist.map((t, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, fontSize: 12 }}>
                <span style={{ flex: 1 }}>{String(t.type || '')}</span>
                <div style={{ flex: 2, height: 8, borderRadius: 4, background: '#F3F4F6', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(100, (Number(t.count) / Math.max(1, ...typeDist.map(d => Number(d.count)))) * 100)}%`, background: '#0F766E', borderRadius: 4 }} />
                </div>
                <span style={{ color: '#6B7280', minWidth: 30, textAlign: 'right' }}>{String(t.count)}</span>
              </div>
            ))}
        </div>

        {/* Risk distribution */}
        <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>风险等级分布</div>
          {riskDist.length === 0 ? <div style={{ fontSize: 12, color: '#9CA3AF' }}>暂无数据</div> :
            riskDist.map((r, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 4, fontSize: 12 }}>
                <span style={{ flex: 1 }}>{String(r.level || '')}</span>
                <span style={{ fontWeight: 600 }}>{String(r.count)}</span>
              </div>
            ))}
        </div>
      </div>

      {/* High Risk Roads */}
      <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB', marginTop: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>高风险路口 ({roads.length})</div>
        {roads.length === 0 ? <div style={{ fontSize: 12, color: '#9CA3AF' }}>暂无数据</div> :
          roads.slice(0, 5).map((r, i) => (
            <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12 }}>
              <strong>{String(r.roadName)}</strong> · {String(r.totalEvents)}起 · 均分{String(r.avgRiskScore)} · 最常见{String(r.mostCommonEventType)}
              <div style={{ color: '#6B7280', fontSize: 11 }}>{String(r.suggestedAction || '').slice(0, 80)}</div>
            </div>
          ))}
      </div>

      {/* Findings & Suggestions */}
      {(findings.length > 0 || suggestions.length > 0) && (
        <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB', marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>管理建议</div>
          {findings.map((f, i) => <div key={i} style={{ fontSize: 12, color: '#374151', padding: '2px 0' }}>· {f}</div>)}
          {suggestions.map((s, i) => <div key={i} style={{ fontSize: 12, color: '#0F766E', padding: '2px 0', fontWeight: 500 }}>→ {s}</div>)}
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        <ChatWorkspace sessionId={undefined} pendingCreate={true} defaultMode="report" showFullModes={false} onSessionCreated={() => {}} onConversationUpdate={() => {}} onNewConversation={() => {}} view="report" />
      </div>
    </div>
  );
}

// ========== Alert Dashboard ==========

function AlertDashboard() {
  const [alerts, setAlerts] = useState<unknown[]>([]);
  const [roads, setRoads] = useState<unknown[]>([]);
  useEffect(() => {
    fetch('/api/alerts/unclosed?hours=720').then(r => r.json()).then(d => setAlerts(d.alerts || [])).catch(() => {});
    fetch('/api/stats/high_risk_roads?days=30').then(r => r.json()).then(d => setRoads(d.topRoads || [])).catch(() => {});
  }, []);
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ background: '#FFF', borderRadius: 16, padding: 16, border: '1px solid #E5E7EB' }}>
        <h3 style={{ fontSize: 15, fontWeight: 600 }}>什么是未闭环事件？</h3>
        <div style={{ fontSize: 12, color: '#6B7280', lineHeight: 1.7, marginBottom: 12 }}>
          未闭环事件 = 已被系统发现和研判，但尚未完成处置闭环的交通事件。闭环流程：发现 → 研判 → 派发 → 处置 → 归档。系统中「待派单」「处置中」「待复盘」等状态为<strong>系统内模拟处置状态</strong>，不代表已接入真实交管系统或已向真实单位派发任务。
        </div>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: '#EF4444' }}>未闭环列表 ({alerts.length})</h3>
        {(alerts as Record<string,unknown>[]).slice(0, 10).map((a, i) => (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12 }}>
            <strong>{String(a.eventId)}</strong> {String(a.eventType)} · {String(a.roadName)} · {String(a.riskLevel)}
            <span style={{ color: '#9CA3AF' }}> · {String(a.durationSinceCreated)}</span>
          </div>
        ))}
      </div>
      <div style={{ background: '#FFF', borderRadius: 16, padding: 16, border: '1px solid #E5E7EB' }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: '#0F766E' }}>高风险路口 TopN</h3>
        {(roads as Record<string,unknown>[]).map((r, i) => (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12 }}>
            <strong>{String(r.roadName)}</strong> · {String(r.totalEvents)}起 · 均分{String(r.avgRiskScore)}
          </div>
        ))}
      </div>
    </div>
  );
}

function GuidePage() { return <div style={{ display: 'grid', gap: 16 }}><div style={{ background: '#FFF', borderRadius: 16, padding: 16, border: '1px solid #E5E7EB', fontSize: 13, lineHeight: 1.8 }}><h3 style={{ fontSize: 15 }}>产品逻辑</h3><p>首次发送自动创建会话；同一会话追问不创建新会话。输入框模式决定分析链路。</p><h3 style={{ fontSize: 15, marginTop: 12 }}>RAG策略</h3><p>query→意图识别→语义召回→docType加权→rerank→阈值过滤→evidence→grounded answer。&lt;0.35拒答</p><h3 style={{ fontSize: 15, marginTop: 12 }}>混合相似度</h3><p>final=rule×w<sub>r</sub>+vector×w<sub>v</sub>。默认0.6/0.4。工程启发式权重。</p></div></div>; }
