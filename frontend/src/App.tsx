import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import LayoutShell from './components/LayoutShell';
import HomeHero from './components/HomeHero';
import ScenarioGrid from './components/ScenarioGrid';
import ChatWorkspace from './components/ChatWorkspace';
import { chatApi, type SessionItem } from './api/chatApi';
import { reduceCollaborationEvent } from './utils/collaborationEventReducer';
import { collabApi } from './api/collaborationApi';
import type { CollaborationRun, CollaborationTask, CollaborationAgentResult } from './types/collaboration';
import CollaborationRunView from './components/collaboration/CollaborationRunView';
import { WorkflowWorkspace } from './components/workflow/WorkflowWorkspace';
import { TrafficMapWorkspace } from './components/simulation/TrafficMapWorkspace';
import { EvaluationDashboard } from './components/evaluation/EvaluationDashboard';
import { KnowledgeWorkspace } from './components/knowledge/KnowledgeWorkspace';
import { PlanCenter } from './components/planning/PlanCenter';
import { RelatedWorkflowRuns } from './components/workflow/RelatedWorkflowRuns';

const WORKSPACE_INFO: Record<string, { title: string; sub: string; showFullModes: boolean; defaultMode: string }> = {
  home: { title: '', sub: '', showFullModes: true, defaultMode: 'react' },
  qa: { title: '知识库', sub: 'RAG交通知识库 · 规则/预案/经验检索 · 证据问答', showFullModes: false, defaultMode: 'rag' },
  report: { title: '统计报告', sub: '日报/周报 · 高风险路口 · 事件趋势 · 管理建议', showFullModes: false, defaultMode: 'report' },
  multi: { title: '协同分析', sub: '多Agent研判 + 冲突检测 + 融合处置建议', showFullModes: false, defaultMode: 'routed' },
  workflow: { title: '工作流中心', sub: '查看运行记录、跟踪执行状态或从模板启动新的工作流', showFullModes: false, defaultMode: 'routed' },
  simulation: { title: '交通态势', sub: '模拟交通环境 · 路网可视化 · 事件注入 · 态势感知', showFullModes: false, defaultMode: 'routed' },
  planning: { title: 'Plan Center', sub: '自适应计划 · 执行血缘 · 重规划轨迹 · 预算与恢复', showFullModes: false, defaultMode: 'routed' },
};

export default function App() {
  // Read sessionId + workflowRunId + simulationRunId + view from URL on mount for refresh persistence
  const urlParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const urlSessionId = urlParams.get('sessionId');
  const urlWorkflowRunId = urlParams.get('workflowRunId');
  const urlSimulationRunId = urlParams.get('simulationRunId');
  const urlView = urlParams.get('view');
  const urlReport = urlParams.get('report');
  const urlPlanId = urlParams.get('planId');
  const urlRootRunId = urlParams.get('rootRunId');
  const urlFromVersion = urlParams.get('fromVersion');
  const urlToVersion = urlParams.get('toVersion');
  const urlEventId = urlParams.get('eventId');
  const urlRoadName = urlParams.get('roadName');
  const urlRisk = urlParams.get('risk');
  const initialSessionId = urlSessionId || null;
  const initialWorkflowRunId = urlWorkflowRunId || null;
  const initialSimulationRunId = urlSimulationRunId || null;

  const VALID_VIEWS = ['home','qa','report','multi','workflow','simulation','evaluation','alert','guide','planning'];
  const [activeSessionId, setActiveSessionId] = useState<string | null>(initialSessionId);
  const [pendingCreate, setPendingCreate] = useState(!initialSessionId);
  const [view, setView] = useState(() => {
    if (urlView && VALID_VIEWS.includes(urlView)) return urlView;
    if (urlReport) return 'evaluation';  // legacy: ?report=xxx without ?view=
    if (urlWorkflowRunId) return 'workflow';
    if (urlSimulationRunId) return 'simulation';
    if (urlPlanId) return 'planning';
    return 'home';
  });
  const [workflowRunId, setWorkflowRunId] = useState<string | null>(initialWorkflowRunId);
  const [planId, setPlanId] = useState<string | null>(urlPlanId || null);
  const [rootRunId, setRootRunId] = useState<string | null>(urlRootRunId || null);
  const [fromVersion, setFromVersion] = useState<number | null>(urlFromVersion ? Number(urlFromVersion) : null);
  const [toVersion, setToVersion] = useState<number | null>(urlToVersion ? Number(urlToVersion) : null);
  const [draftInput, setDraftInput] = useState('');
  const [draftMode, setDraftMode] = useState('react');
  // Phase20 R2：Traffic 视图深度链接聚焦（真实持久化 ID / 路段名 / 风险过滤）
  const [trafficEventId, setTrafficEventId] = useState<string | null>(urlEventId || null);
  const [trafficRoadName, setTrafficRoadName] = useState<string | null>(urlRoadName || null);
  const [trafficRisk, setTrafficRisk] = useState<string | null>(urlRisk || null);
  const [recentRefresh, setRecentRefresh] = useState(0);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  // Stable key: only change when we WANT to reset the workspace (new conv / recent click)
  const [workspaceKey, setWorkspaceKey] = useState(0);

  // Stable session ID ref — prevents stale closure in callbacks
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => { sessionIdRef.current = activeSessionId; }, [activeSessionId]);

  // Update URL when active session or workflow run changes
  const updateUrl = useCallback((sid: string | null, wfRunId?: string | null) => {
    const url = new URL(window.location.href);
    if (sid) {
      url.searchParams.set('sessionId', sid);
    } else {
      url.searchParams.delete('sessionId');
    }
    if (wfRunId !== undefined) {
      if (wfRunId) {
        url.searchParams.set('workflowRunId', wfRunId);
      } else {
        url.searchParams.delete('workflowRunId');
      }
    }
    window.history.replaceState({}, '', url.toString());
  }, []);

  // Handle workflowRunId changes (from WorkflowWorkspace)
  const handleWorkflowRunIdChange = useCallback((newRunId: string | null) => {
    setWorkflowRunId(newRunId);
    updateUrl(activeSessionId, newRunId);
  }, [activeSessionId, updateUrl]);

  // Phase17 P1: planning URL state
  const updatePlanningUrl = useCallback((p: string | null, root: string | null, fv: number | null, tv: number | null) => {
    const url = new URL(window.location.href);
    if (p) url.searchParams.set('planId', p); else url.searchParams.delete('planId');
    if (root) url.searchParams.set('rootRunId', root); else url.searchParams.delete('rootRunId');
    if (fv) url.searchParams.set('fromVersion', String(fv)); else url.searchParams.delete('fromVersion');
    if (tv) url.searchParams.set('toVersion', String(tv)); else url.searchParams.delete('toVersion');
    window.history.replaceState({}, '', url.toString());
  }, []);

  const handlePlanSelect = useCallback((p: string) => {
    setPlanId(p || null);
    setRootRunId(null);
    setFromVersion(null); setToVersion(null);
    updatePlanningUrl(p || null, null, null, null);
  }, [updatePlanningUrl]);

  const handleRootRunIdChange = useCallback((root: string | null) => {
    setRootRunId(root);
    updatePlanningUrl(planId, root, fromVersion, toVersion);
  }, [planId, fromVersion, toVersion, updatePlanningUrl]);

  const handleDiffChange = useCallback((fv: number | null, tv: number | null) => {
    setFromVersion(fv); setToVersion(tv);
    updatePlanningUrl(planId, rootRunId, fv, tv);
  }, [planId, rootRunId, updatePlanningUrl]);

  const handleOpenWorkflowRun = useCallback((runId: string) => {
    setWorkflowRunId(runId);
    setView('workflow');
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'workflow');
    url.searchParams.set('workflowRunId', runId);
    url.searchParams.delete('planId');
    url.searchParams.delete('rootRunId');
    url.searchParams.delete('fromVersion');
    url.searchParams.delete('toVersion');
    // 用户跨视图导航（Plan → Workflow）→ pushState，使 Browser Back 可回 Plan Center
    window.history.pushState({}, '', url.toString());
  }, []);

  // Phase20 R2：Run → Plan（authority: definitionId == planId，仅 plan 物化定义成立）
  const handleOpenPlan = useCallback((planIdValue: string) => {
    setView('planning');
    setPlanId(planIdValue);
    setRootRunId(null); setFromVersion(null); setToVersion(null);
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'planning');
    url.searchParams.set('planId', planIdValue);
    url.searchParams.delete('workflowRunId');
    url.searchParams.delete('rootRunId');
    url.searchParams.delete('fromVersion');
    url.searchParams.delete('toVersion');
    window.history.pushState({}, '', url.toString());
  }, []);

  // Phase20 R2：Risk → Traffic 事件聚焦（authority: 真实 event_records eventId）
  const handleOpenTrafficEvent = useCallback((eventId: string) => {
    setView('simulation');
    setWorkflowRunId(null);
    setTrafficEventId(eventId);
    setTrafficRoadName(null);
    setTrafficRisk(null);
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'simulation');
    url.searchParams.set('eventId', eventId);
    url.searchParams.delete('workflowRunId');
    url.searchParams.delete('roadName');
    url.searchParams.delete('risk');
    window.history.pushState({}, '', url.toString());
  }, []);

  // Phase20 R2：高风险路口 → Traffic 路段过滤（authority: 真实 roadName 值）
  const handleOpenTrafficRoad = useCallback((roadName: string) => {
    setView('simulation');
    setWorkflowRunId(null);
    setTrafficRoadName(roadName);
    setTrafficEventId(null);
    setTrafficRisk(null);
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'simulation');
    url.searchParams.set('roadName', roadName);
    url.searchParams.delete('workflowRunId');
    url.searchParams.delete('eventId');
    url.searchParams.delete('risk');
    window.history.pushState({}, '', url.toString());
  }, []);

  // Phase20 R2：高风险事件 KPI → Traffic 风险过滤（authority: 真实 riskLevel 枚举）
  const handleOpenTrafficRisk = useCallback((risk: string) => {
    setView('simulation');
    setWorkflowRunId(null);
    setTrafficRisk(risk);
    setTrafficEventId(null);
    setTrafficRoadName(null);
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'simulation');
    url.searchParams.set('risk', risk);
    url.searchParams.delete('workflowRunId');
    url.searchParams.delete('eventId');
    url.searchParams.delete('roadName');
    window.history.pushState({}, '', url.toString());
  }, []);

  // Traffic 面板清除深度链接聚焦（用户主动清除，replaceState 不产生历史条目）
  const handleClearTrafficFocus = useCallback(() => {
    setTrafficEventId(null);
    setTrafficRoadName(null);
    setTrafficRisk(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('eventId');
    url.searchParams.delete('roadName');
    url.searchParams.delete('risk');
    window.history.replaceState({}, '', url.toString());
  }, []);

  // Browser Back / Forward：重新从 URL 解析并同步 React view/state
  useEffect(() => {
    const onPopState = () => {
      const params = new URLSearchParams(window.location.search);
      const v = params.get('view');
      if (v && VALID_VIEWS.includes(v)) setView(v);
      else if (params.get('workflowRunId')) setView('workflow');
      else if (params.get('planId')) setView('planning');
      setWorkflowRunId(params.get('workflowRunId'));
      setPlanId(params.get('planId'));
      setRootRunId(params.get('rootRunId'));
      const fv = params.get('fromVersion');
      const tv = params.get('toVersion');
      setFromVersion(fv ? Number(fv) : null);
      setToVersion(tv ? Number(tv) : null);
      setTrafficEventId(params.get('eventId'));
      setTrafficRoadName(params.get('roadName'));
      setTrafficRisk(params.get('risk'));
      const sid = params.get('sessionId');
      if (sid) setActiveSessionId(sid);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  // On mount: normalize legacy URLs (e.g. ?report=xxx without ?view=evaluation)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('report') && !params.get('view')) {
      const url = new URL(window.location.href);
      url.searchParams.set('view', 'evaluation');
      window.history.replaceState({}, '', url.toString());
    }
  }, []);

  // On mount: if URL has sessionId, load it and set the correct view.
  // Guard: if URL already has an explicit `view` (e.g. ?view=workflow&workflowRunId=...),
  // do NOT override it from session mode — this caused F5 to jump from Workflow Run Detail
  // back to Knowledge when a stale sessionId was also present.
  useEffect(() => {
    if (!initialSessionId) return;
    if (urlView) return;
    chatApi.getSession(initialSessionId).then(detail => {
      const m = detail.session.mode || 'react';
      const vm: Record<string,string> = { react:'home',routed:'home',hybrid:'home',rag:'qa',collaboration:'multi',report:'report',simulation:'simulation' };
      setView(vm[m] || 'home');
    }).catch(() => setView('home'));
  }, [initialSessionId, urlView]);

  useEffect(() => { chatApi.listSessions(30).then(setSessions).catch(() => {}); }, [recentRefresh]);
  const refreshSessions = useCallback(() => setRecentRefresh(Date.now()), []);
  // CRITICAL: session created via first send — do NOT reset the component (key stays same)
  const handleSessionCreated = useCallback((id: string) => { sessionIdRef.current = id; setActiveSessionId(id); setPendingCreate(false); setRecentRefresh(Date.now()); updateUrl(id); }, []);
  const handleNewConversation = () => { sessionIdRef.current = null; setActiveSessionId(null); setPendingCreate(true); setDraftInput(''); setView('home'); setWorkspaceKey(k => k + 1); updateUrl(null); };
  const handleScenario = (prompt: string, mode: string, targetView: string) => { sessionIdRef.current = null; setDraftInput(prompt); setDraftMode(mode); setView(targetView); setActiveSessionId(null); setPendingCreate(true); setWorkspaceKey(k => k + 1); updateUrl(null); };
  const handleNavigate = (v: string) => {
    setView(v);
    const url = new URL(window.location.href);
    url.searchParams.set('view', v);
    if (v !== 'evaluation') url.searchParams.delete('report');
    if (v === 'workflow') {
      // Explicit nav to workflow → clear run detail, show center
      setWorkflowRunId(null);
      url.searchParams.delete('workflowRunId');
      // 清除知识库/会话残留参数，避免两套 URL state 互污染
      setActiveSessionId(null);
      url.searchParams.delete('sessionId');
      url.searchParams.delete('knowledgeTab');
      url.searchParams.delete('knowledgeDocumentId');
      url.searchParams.delete('knowledgeChunkId');
    }
    if (v === 'qa') {
      // Explicit nav to 知识库 → enter default Documents tab, clear stale RAG session
      setActiveSessionId(null);
      setPendingCreate(true);
      url.searchParams.delete('sessionId');
      url.searchParams.delete('knowledgeTab');
      url.searchParams.delete('knowledgeDocumentId');
      url.searchParams.delete('knowledgeChunkId');
      // 清除工作流残留参数
      setWorkflowRunId(null);
      url.searchParams.delete('workflowRunId');
    }
    if (v === 'planning') {
      // Explicit nav to Plan Center → clear workflow/knowledge params + show list
      setWorkflowRunId(null);
      setActiveSessionId(null);
      setPlanId(null); setRootRunId(null); setFromVersion(null); setToVersion(null);
      url.searchParams.delete('workflowRunId');
      url.searchParams.delete('sessionId');
      url.searchParams.delete('knowledgeTab');
      url.searchParams.delete('knowledgeDocumentId');
      url.searchParams.delete('knowledgeChunkId');
      url.searchParams.delete('planId');
      url.searchParams.delete('rootRunId');
      url.searchParams.delete('fromVersion');
      url.searchParams.delete('toVersion');
    }
    if (v === 'simulation') {
      // Explicit nav to 交通态势 → clear traffic deep-link focus params
      setTrafficEventId(null);
      setTrafficRoadName(null);
      setTrafficRisk(null);
      url.searchParams.delete('eventId');
      url.searchParams.delete('roadName');
      url.searchParams.delete('risk');
    }
    // 离开 planning 时清理 planning 残留参数
    if (v !== 'planning') {
      url.searchParams.delete('planId');
      url.searchParams.delete('rootRunId');
      url.searchParams.delete('fromVersion');
      url.searchParams.delete('toVersion');
    }
    // 用户显式切换主 view（sidebar）→ pushState，使 Browser Back 符合预期
    window.history.pushState({}, '', url.toString());
  };
  const handleRecentClick = async (id: string) => {
    // Fetch session to determine its mode, then route to correct workspace
    let targetView = 'home';
    try {
      const detail = await chatApi.getSession(id);
      const sessionMode = detail.session.mode || 'react';
      const viewMap: Record<string, string> = {
        react: 'home', routed: 'home', hybrid: 'home',
        rag: 'qa', collaboration: 'multi', report: 'report',
        simulation: 'simulation',
      };
      targetView = viewMap[sessionMode] || 'home';
    } catch {
      targetView = 'home';
    }
    setView(targetView);
    setActiveSessionId(id); setPendingCreate(false); setDraftInput(''); setWorkspaceKey(k => k + 1);
    // Update URL atomically: view + sessionId + knowledgeTab (for RAG ask tab)
    const url = new URL(window.location.href);
    url.searchParams.set('view', targetView);
    url.searchParams.set('sessionId', id);
    if (targetView === 'qa') {
      url.searchParams.set('knowledgeTab', 'ask');
    }
    // 用户点击 recent session → 视图切换 → pushState
    window.history.pushState({}, '', url.toString());
  };
  const handleRenameSession = async (id: string, t: string) => { try { await fetch(`/api/chat/sessions/${id}/title`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: t }) }); refreshSessions(); } catch { /* ignore */ } };
  const handleDeleteSession = async (sessionId: string) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    let deleted = false;
    try {
      const resp = await fetch(`/api/chat/sessions/${sessionId}`, {
        method: 'DELETE',
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      deleted = resp.ok || resp.status === 404;
      if (!deleted) {
        console.error(`Delete session ${sessionId} failed: HTTP ${resp.status}`);
      }
      if (activeSessionId === sessionId) {
        sessionIdRef.current = null;
        setActiveSessionId(null);
        setPendingCreate(true);
        setView('home');
        setWorkspaceKey(k => k + 1);
      }
    } catch (err: unknown) {
      clearTimeout(timeoutId);
      if (err instanceof DOMException && err.name === 'AbortError') {
        console.error('Delete session timed out');
      } else {
        console.error('Delete session failed:', err);
      }
    } finally {
      // Always refresh list (fire-and-forget — don't block modal close)
      if (deleted) refreshSessions();
      else setTimeout(() => refreshSessions(), 200); // slight delay so error can be seen
    }
  };
  const info = WORKSPACE_INFO[view] || WORKSPACE_INFO.home;
  // Dedup by session ID — same sessionId = 1 sidebar entry
  const recentItems = Array.from(
    new Map(sessions.map(s => [s.id, { id: s.id, title: s.title || '未命名交通分析', mode: s.mode, updatedAt: new Date(s.updated_at).getTime() }])).values()
  );

  return (
    <LayoutShell activeView={view} onNavigate={handleNavigate} onRecentClick={handleRecentClick} onNewConversation={handleNewConversation} onRenameSession={handleRenameSession} onDeleteSession={handleDeleteSession} activeConvId={activeSessionId || undefined} recentList={recentItems}>
      <div style={view === 'simulation' ? { width: '100%', padding: '16px 24px 32px' } as React.CSSProperties : { maxWidth: 960, margin: '0 auto', width: '100%', padding: '0 24px 32px' }}>
        {view === 'alert' ? <AlertDashboard onOpenEvent={handleOpenTrafficEvent} onOpenRoad={handleOpenTrafficRoad} onOpenRun={handleOpenWorkflowRun} /> :
         view === 'guide' ? <GuidePage /> :
         view === 'report' ? <ReportDashboard onOpenRoad={handleOpenTrafficRoad} onOpenRisk={handleOpenTrafficRisk} /> :
         view === 'qa' ? <KnowledgeWorkspace onRefresh={refreshSessions} activeSessionId={activeSessionId || undefined} /> :
         view === 'multi' ? <CollaborationWorkspace activeSessionId={activeSessionId || null} onRefresh={refreshSessions} onSessionCreated={handleSessionCreated} onOpenRun={handleOpenWorkflowRun} /> :
         view === 'workflow' ? <WorkflowWorkspace workflowRunId={workflowRunId} sessionId={activeSessionId} onRunIdChange={handleWorkflowRunIdChange} onOpenRun={handleOpenWorkflowRun} onOpenPlan={handleOpenPlan} /> :
         view === 'simulation' ? <TrafficMapWorkspace workflowRunId={workflowRunId} onWorkflowRunIdChange={handleWorkflowRunIdChange} onOpenWorkflowRun={handleOpenWorkflowRun} focusEventId={trafficEventId} focusRoadName={trafficRoadName} focusRisk={trafficRisk} onClearFocus={handleClearTrafficFocus} /> :
         view === 'planning' ? <PlanCenter planId={planId} rootRunId={rootRunId} fromVersion={fromVersion} toVersion={toVersion} onPlanSelect={handlePlanSelect} onRootRunIdChange={handleRootRunIdChange} onDiffChange={handleDiffChange} onOpenWorkflowRun={handleOpenWorkflowRun} /> :
         view === 'evaluation' ? <EvaluationDashboard /> : (
          <>
            <HomeHero />
            <ScenarioGrid onSelect={handleScenario} />
            <ChatWorkspace key={workspaceKey} sessionId={activeSessionId || undefined} pendingCreate={pendingCreate} draftInput={draftInput} draftMode={draftMode} onDraftConsumed={() => setDraftInput('')} defaultMode={info.defaultMode} showFullModes={info.showFullModes} onSessionCreated={handleSessionCreated} onConversationUpdate={refreshSessions} onNewConversation={handleNewConversation} view={view} onOpenWorkflowRun={handleOpenWorkflowRun} />
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

function CollaborationWorkspace({ activeSessionId, onRefresh, onSessionCreated, onOpenRun }: { activeSessionId: string | null; onRefresh: () => void; onSessionCreated: (id: string) => void; onOpenRun: (runId: string) => void }) {
  return <CollaborationWorkspaceInner activeSessionId={activeSessionId} onRefresh={onRefresh} onSessionCreated={onSessionCreated} onOpenRun={onOpenRun} />;
}

function CollaborationWorkspaceInner({ activeSessionId, onRefresh, onSessionCreated, onOpenRun }: { activeSessionId: string | null; onRefresh: () => void; onSessionCreated: (id: string) => void; onOpenRun: (runId: string) => void }) {
  // Core multi-run state
  const [activeRunId, setActiveRunId] = useState<string>('');
  const [runsById, setRunsById] = useState<Record<string, CollaborationRun>>({});
  const [runList, setRunList] = useState<{ run_id: string; status: string }[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Record<string, unknown>[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const isSubmitting = useRef(false);
  // Stable session ID — ONLY writes happen via session_created or explicit history click.
  // NEVER reset to null except via handleNewConversation.
  const sessionIdRef = useRef<string | null>(null);
  // Sync from prop ONLY when prop changes to a different non-null value (e.g. history click)
  useEffect(() => {
    if (activeSessionId && activeSessionId !== sessionIdRef.current) {
      console.log('[COLLAB] sessionIdRef sync from prop:', activeSessionId);
      sessionIdRef.current = activeSessionId;
    }
  }, [activeSessionId]);

  // Mount/unmount tracking
  const mountRef = useRef(0);
  useEffect(() => {
    mountRef.current += 1;
    console.log('[COLLAB] CollaborationWorkspaceInner mounted #', mountRef.current, 'activeSessionId=', activeSessionId);
    return () => { console.log('[COLLAB] CollaborationWorkspaceInner unmounting #', mountRef.current); };
  }, []);

  // Derived: active run
  const activeRun = activeRunId ? runsById[activeRunId] || null : null;

  // Unified deserializer — single source of truth for API → CollaborationRun
  const deserializeRunDetail = (detail: Record<string,unknown>, runId: string): CollaborationRun => {
    const run = (detail.run || detail) as Record<string,unknown>;
    const rawTasks = (detail.tasks || []) as Record<string,unknown>[];
    const tasks: CollaborationTask[] = rawTasks.map((t: Record<string,unknown>) => ({
      taskId: String(t.taskId ?? t.task_id ?? ''), agentName: String(t.agentName ?? t.agent_name ?? ''),
      taskType: String(t.taskType ?? t.task_type ?? 'analyze'),
      status: (t.status as CollaborationTask['status']) || 'succeeded',
      dependsOn: parseJson<string[]>(t.dependsOn ?? t.depends_on, []),
      priority: Number(t.priority || 5), attempt: Number(t.attempt || 1),
      maxRetries: Number(t.maxRetries ?? t.max_retries ?? 1),
      timeoutSeconds: Number(t.timeoutSeconds ?? t.timeout_seconds ?? 30),
      error: String(t.error ?? t.error_message ?? ''),
    }));

    const agentResults: Record<string, CollaborationAgentResult> = {};
    for (const t of rawTasks) {
      const os = parseJson<Record<string,unknown>>(t.output_snapshot ?? t.outputSnapshot, {});
      const an = String(t.agentName ?? t.agent_name ?? '');
      if (an && Object.keys(os).length > 0 && !['ConflictDetector', 'FusionAgent'].includes(an)) {
        agentResults[an] = {
          agentName: an, role: '', status: 'completed',
          findings: (os.findings || []) as string[],
          confidence: Number(os.confidence || 0),
          suggestion: (os.suggestion || os.recommendation || '') as string,
          urgency: (os.urgency || 'low') as string,
          evidenceRefs: (os.evidenceRefs || []) as string[],
          attempt: 1, duration: 0,
        };
      }
    }

    const fdRaw = run.final_decision ?? run.finalDecision;
    const fd: Record<string,unknown> = typeof fdRaw === 'string' ? parseJson(fdRaw, {}) : (fdRaw as Record<string,unknown>) || {};
    const budgetRaw = run.budget_usage ?? run.budgetUsage;
    const budget: CollaborationRun['budgetUsage'] = typeof budgetRaw === 'string'
      ? parseJson(budgetRaw, { maxAgents: 6, maxAgentCalls: 2, maxRetries: 2, maxTotalSeconds: 120, usedAgentCalls: {}, usedRetries: {}, startedAt: '' })
      : (budgetRaw as unknown as CollaborationRun['budgetUsage']) || { maxAgents: 6, maxAgentCalls: 2, maxRetries: 2, maxTotalSeconds: 120, usedAgentCalls: {}, usedRetries: {}, startedAt: '' };

    return {
      runId: runId, traceId: String(run.trace_id ?? run.traceId ?? ''),
      sessionId: String(run.session_id ?? run.sessionId ?? ''),
      status: (run.status as CollaborationRun['status']) || 'completed',
      executionEngine: 'orchestrator', protocolVersion: '1.0',
      selectedAgents: parseJson<string[]>(run.selected_agents ?? run.selectedAgents, []),
      skippedAgents: parseJson<string[]>(run.skipped_agents ?? run.skippedAgents, []),
      routingReasons: [], tasks,
      agentResults, conflicts: [], arbitrationResults: [],
      failedAgents: parseJson<string[]>(run.failed_agents ?? run.failedAgents, []),
      limitations: [], budgetUsage: budget,
      finalDecision: String(run.final_decision ?? run.finalDecision ?? ''),
      fusionSummary: fd.fusionSummary as string || fd.fusion_summary as string || '',
      requiresHumanReview: Boolean(fd.requiresHumanReview ?? fd.requires_human_review),
      degraded: false, fallbackReason: '',
      startedAt: String(run.started_at ?? run.startedAt ?? ''),
      completedAt: String(run.updated_at ?? run.updatedAt ?? ''),
      isHydrated: true,
      userQuery: String(run.userQuery ?? ''),
      contextPolicy: String(run.contextPolicy ?? 'fresh_event'),
      fieldSources: parseJson<Record<string,string>>(run.fieldSources ?? run.field_sources, {}),
    };
  };

  // Hydrate run detail — works even when runsById is empty (history recovery)
  const hydrateRun = (runId: string) => {
    if (!runId) return;
    const existing = runsById[runId];
    if (existing?.isHydrated) return; // already fully loaded

    collabApi.getRun(runId).then(detail => {
      const r = deserializeRunDetail(detail, runId);
      setRunsById(prev => {
        const cur = prev[runId];
        // Preserve SSE-derived fields if they exist; API data is authoritative for static fields
        const merged: CollaborationRun = {
          ...(cur || createEmptyRun(r.sessionId)),
          ...r,
          // NEVER overwrite live fusionSummary from SSE with empty API value
          fusionSummary: r.fusionSummary || cur?.fusionSummary || '',
          isHydrated: true,
        };
        return { ...prev, [runId]: merged };
      });
    }).catch(() => {});
  };

  // When activeRunId changes to a non-hydrated run, hydrate it
  useEffect(() => {
    if (activeRunId) hydrateRun(activeRunId);
  }, [activeRunId]);

  // Chronological sort: started_at ASC, run_id ASC fallback
  const sortRunsChronologically = <T extends { run_id: string; started_at?: string; startedAt?: string }>(runs: T[]): T[] => {
    return [...runs].sort((a, b) => {
      const aTime = Date.parse(String((a as Record<string,unknown>).started_at ?? (a as Record<string,unknown>).startedAt ?? ''));
      const bTime = Date.parse(String((b as Record<string,unknown>).started_at ?? (b as Record<string,unknown>).startedAt ?? ''));
      if (Number.isFinite(aTime) && Number.isFinite(bTime) && aTime !== bTime) {
        return aTime - bTime;
      }
      return String(a.run_id).localeCompare(String(b.run_id));
    });
  };

  // Load history if session exists (only on initial mount or session change)
  useEffect(() => {
    if (!activeSessionId) { setRunsById({}); setRunList([]); setActiveRunId(''); setMessages([]); return; }
    fetch(`/api/chat/sessions/${activeSessionId}`).then(r => r.json()).then(d => setMessages(d.messages || [])).catch(() => {});
    collabApi.listSessionRuns(activeSessionId).then(items => {
      const ordered = sortRunsChronologically(items);
      setRunList(ordered);
      if (ordered.length > 0) {
        const latestId = String(ordered[ordered.length - 1].run_id);
        setActiveRunId(latestId);
        // Immediately hydrate the latest run — works even with empty runsById
        hydrateRun(latestId);
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

    const submittedSessionId = sessionIdRef.current;
    console.log('[COLLAB] handleAnalyze: sessionIdRef.current=', submittedSessionId, 'prop.activeSessionId=', activeSessionId);
    let currentRun = createEmptyRun(submittedSessionId || '');

    const clientRequestId = 'req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);

    // Detect context policy: if the user mentions continuing or "上述", use continue_event
    const followUpPattern = /(继续|基于上|上述|刚才|同一|沿用)/;
    const explicitValuePattern = /(\d+\.?\d*)\s*(?:km\/h|公里|码|米|m|分钟|分)/;
    const contextPolicy = followUpPattern.test(question) && !explicitValuePattern.test(question)
      ? 'continue_event' : 'fresh_event';

    // Only send NL content — backend parser extracts structured fields from text.
    // Dynamic measurements (avgSpeed, queueLength, duration) are NEVER pre-filled.
    await collabApi.streamCollaboration(
      { sessionId: submittedSessionId, content: question, mode: 'collaboration', clientRequestId, contextPolicy },
      {
        onEvent: (event) => {
          // session_created has NO runId — must be handled FIRST, before runId guard
          if (event.eventType === 'session_created' && event.sessionId) {
            const sid = event.sessionId as string;
            console.log('[COLLAB] session_created:', sid);
            sessionIdRef.current = sid;
            onSessionCreated(sid);
            onRefresh();
            return;
          }

          const evRunId = (event.runId as string) || '';
          if (!evRunId) return;

          // Fallback: if run event carries sessionId not yet in ref, sync it
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
            console.log('[COLLAB] run_created:', evRunId, 'sessionIdRef.current=', sessionIdRef.current);
            setRunList(prev => {
              if (prev.some(r => r.run_id === evRunId)) return prev;
              const merged = [...prev, { run_id: evRunId, status: 'running' as const, started_at: new Date().toISOString() } as { run_id: string; status: string; started_at?: string }];
              return sortRunsChronologically(merged);
            });
            setActiveRunId(evRunId);
          }
          // Update runList status on completion
          if (event.eventType === 'done' || event.eventType === 'run_completed') {
            console.log('[COLLAB] done/run_completed:', evRunId, 'sessionIdRef.current=', sessionIdRef.current);
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

  const handleSelectRun = (runId: string) => {
    setActiveRunId(runId);
    // If not yet hydrated, load from API; otherwise cached data is used
    if (!runsById[runId]?.isHydrated) {
      hydrateRun(runId);
    }
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

      {/* Chat messages — only show when no runs exist (old data fallback) */}
      {messages.length > 0 && runList.length === 0 && !activeRun && (
        <div style={{ marginBottom: 12 }}>
          {messages.map((m: Record<string,unknown>, i: number) => (
            <div key={i} style={{ padding: '6px 0', fontSize: 12, color: '#374151' }}>
              <strong>{m.role === 'user' ? '你' : 'TrafficMind'}:</strong> {String(m.content || '').slice(0, 200)}
            </div>
          ))}
        </div>
      )}

      {/* Loading skeleton while hydrating run detail */}
      {runList.length > 0 && !activeRun && (
        <div style={{ background: '#FFF', borderRadius: 14, padding: 20, border: '1px solid #E5E7EB', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: '#9CA3AF' }}>正在恢复协同运行详情...</div>
        </div>
      )}

      {/* Collaboration Run View */}
      {activeRun && <CollaborationRunView run={activeRun} />}

      {/* Phase20 R2：相关 Workflow Runs（session-level 真实关系，0..N 全部展示） */}
      {sessionIdRef.current && (
        <RelatedWorkflowRuns sessionId={sessionIdRef.current} onOpenRun={onOpenRun} />
      )}
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

// ========== Report Dashboard ==========

function ReportDashboard({ onOpenRoad, onOpenRisk }: { onOpenRoad: (roadName: string) => void; onOpenRisk: (risk: string) => void }) {
  const [stats, setStats] = useState<Record<string,unknown>>({});
  const [roads, setRoads] = useState<Record<string,unknown>[]>([]);
  const [daily, setDaily] = useState<Record<string,unknown> | null>(null);
  useEffect(() => {
    fetch('/api/stats').then(r => r.json()).then(setStats).catch(() => {});
    fetch('/api/stats/high_risk_roads?days=30').then(r => r.json()).then(d => setRoads(d.topRoads || [])).catch(() => {});
    fetch('/api/reports/daily').then(r => r.json()).then(setDaily).catch(() => {});
  }, []);

  const typeDist = (stats.eventTypeDistribution as Record<string,unknown>[]) || [];
  const riskDist = (stats.riskDistribution as Record<string,unknown>[]) || [];
  const findings = (daily?.keyFindings as string[]) || [];
  const suggestions = (daily?.suggestions as string[]) || [];

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 12px' }}>统计报告</h2>
      {/* Top metrics — 高风险卡片点击 → 交通态势按风险等级过滤（明确 filter scope，不伪造 eventId） */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 14 }}>
        {[{ l: '总事件数', v: String(stats.totalEvents || 0), c: '#0F766E', click: null }, { l: '高风险', v: String(stats.highRiskCount || 0), c: '#EF4444', click: '高风险' }, { l: '待处置', v: String(stats.pendingDispatch || 0), c: '#F59E0B', click: null }, { l: '平均风险分', v: String(stats.avgRiskScore || 0), c: '#3B82F6', click: null }].map(x => (
          <div key={x.l}
            onClick={x.click ? () => onOpenRisk(x.click as string) : undefined}
            title={x.click ? '跳转交通态势并按风险等级过滤' : undefined}
            style={{ background: '#FFF', borderRadius: 14, padding: '12px 16px', border: '1px solid #E5E7EB', cursor: x.click ? 'pointer' : undefined }}>
            <div style={{ fontSize: 11, color: '#9CA3AF' }}>{x.l}{x.click && <span style={{ marginLeft: 6, color: '#3B82F6' }}>查看 →</span>}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: x.c }}>{x.v}</div>
          </div>
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

        {/* Risk distribution — 点击行 → 交通态势按该风险等级过滤 */}
        <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>风险等级分布</div>
          {riskDist.length === 0 ? <div style={{ fontSize: 12, color: '#9CA3AF' }}>暂无数据</div> :
            riskDist.map((r, i) => (
              <div key={i} onClick={() => r.level && onOpenRisk(String(r.level))} title={r.level ? '跳转交通态势并按风险等级过滤' : undefined}
                style={{ display: 'flex', gap: 8, marginBottom: 4, fontSize: 12, cursor: r.level ? 'pointer' : undefined }}>
                <span style={{ flex: 1 }}>{String(r.level || '')}</span>
                <span style={{ fontWeight: 600 }}>{String(r.count)}</span>
                <span style={{ color: '#3B82F6', fontSize: 11 }}>查看 →</span>
              </div>
            ))}
        </div>
      </div>

      {/* High Risk Roads — 查看该路段事件 → view=simulation&roadName= */}
      <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB', marginTop: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>高风险路口 ({roads.length})</div>
        {roads.length === 0 ? <div style={{ fontSize: 12, color: '#9CA3AF' }}>暂无数据</div> :
          roads.slice(0, 5).map((r, i) => (
            <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <strong>{String(r.roadName)}</strong> · {String(r.totalEvents)}起 · 均分{String(r.avgRiskScore)} · 最常见{String(r.mostCommonEventType)}
                <div style={{ color: '#6B7280', fontSize: 11 }}>{String(r.suggestedAction || '').slice(0, 80)}</div>
              </div>
              {Boolean(r.roadName) && (
                <button onClick={() => onOpenRoad(String(r.roadName))}
                  style={{ padding: '2px 10px', borderRadius: 6, border: '1px solid #BFDBFE', background: '#EFF6FF', color: '#2563EB', cursor: 'pointer', fontSize: 11, flexShrink: 0 }}>
                  查看该路段事件 →
                </button>
              )}
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

function AlertDashboard({ onOpenEvent, onOpenRoad, onOpenRun }: { onOpenEvent: (eventId: string) => void; onOpenRoad: (roadName: string) => void; onOpenRun: (runId: string) => void }) {
  const [alerts, setAlerts] = useState<unknown[]>([]);
  const [roads, setRoads] = useState<unknown[]>([]);
  // Phase20 R2：每条提醒可展开「相关 Workflow Runs」（真实关系 0..N，绝不默认挑 latest）
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
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
        {(alerts as Record<string,unknown>[]).slice(0, 10).map((a, i) => {
          const eventId = String(a.eventId || '');
          const expanded = expandedEvent === eventId && Boolean(eventId);
          return (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <strong style={{ fontFamily: 'monospace', fontSize: 11 }}>{eventId}</strong>
                <span>{String(a.eventType)} · {String(a.roadName)} · {String(a.riskLevel)}</span>
                <span style={{ color: '#9CA3AF' }}> · {String(a.durationSinceCreated)}</span>
                {eventId && (
                  <button onClick={() => onOpenEvent(eventId)}
                    style={{ padding: '1px 8px', borderRadius: 6, border: '1px solid #BFDBFE', background: '#EFF6FF', color: '#2563EB', cursor: 'pointer', fontSize: 10 }}>
                    查看事件 →
                  </button>
                )}
                {eventId && (
                  <button onClick={() => setExpandedEvent(expanded ? null : eventId)}
                    style={{ padding: '1px 8px', borderRadius: 6, border: '1px solid #99F6E4', background: '#F0FDFA', color: '#0F766E', cursor: 'pointer', fontSize: 10 }}>
                    {expanded ? '收起相关运行' : '相关运行'}
                  </button>
                )}
              </div>
              {expanded && <RelatedWorkflowRuns eventId={eventId} onOpenRun={onOpenRun} />}
            </div>
          );
        })}
        {(alerts as Record<string,unknown>[]).length === 0 && (
          <div style={{ fontSize: 12, color: '#9CA3AF', padding: '8px 0' }}>当前没有未闭环事件</div>
        )}
      </div>
      <div style={{ background: '#FFF', borderRadius: 16, padding: 16, border: '1px solid #E5E7EB' }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: '#0F766E' }}>高风险路口 TopN</h3>
        {(roads as Record<string,unknown>[]).map((r, i) => (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <span><strong>{String(r.roadName)}</strong> · {String(r.totalEvents)}起 · 均分{String(r.avgRiskScore)}</span>
            {Boolean(r.roadName) && (
              <button onClick={() => onOpenRoad(String(r.roadName))}
                style={{ padding: '1px 8px', borderRadius: 6, border: '1px solid #BFDBFE', background: '#EFF6FF', color: '#2563EB', cursor: 'pointer', fontSize: 10, flexShrink: 0 }}>
                查看该路段事件 →
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function GuidePage() { return <div style={{ display: 'grid', gap: 16 }}><div style={{ background: '#FFF', borderRadius: 16, padding: 16, border: '1px solid #E5E7EB', fontSize: 13, lineHeight: 1.8 }}><h3 style={{ fontSize: 15 }}>产品逻辑</h3><p>首次发送自动创建会话；同一会话追问不创建新会话。输入框模式决定分析链路。</p><h3 style={{ fontSize: 15, marginTop: 12 }}>RAG策略</h3><p>query→意图识别→语义召回→docType加权→rerank→阈值过滤→evidence→grounded answer。&lt;0.35拒答</p><h3 style={{ fontSize: 15, marginTop: 12 }}>混合相似度</h3><p>final=rule×w<sub>r</sub>+vector×w<sub>v</sub>。默认0.6/0.4。工程启发式权重。</p></div></div>; }
