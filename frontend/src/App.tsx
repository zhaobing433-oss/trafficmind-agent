import { useState, useCallback, useEffect } from 'react';
import LayoutShell from './components/LayoutShell';
import HomeHero from './components/HomeHero';
import ScenarioGrid from './components/ScenarioGrid';
import ChatWorkspace from './components/ChatWorkspace';
import { chatApi, type SessionItem } from './api/chatApi';
import { streamRoutedAnalyze } from './api/streamApi';

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
         view === 'multi' ? <MultiAgentWorkspace onRefresh={refreshSessions} /> : (
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

function MultiAgentWorkspace({ onRefresh }: { onRefresh: () => void }) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState('');
  const [summary, setSummary] = useState<string>('');

  const handleAnalyze = async () => {
    if (!input.trim() || loading) return;
    setLoading(true); setSummary('');
    // Initialize steps immediately — before any await
    const initSteps: Step[] = [
      { id: 'parse', agentName: '系统', status: 'thinking', message: '正在解析事件信息...' },
      { id: 'route', agentName: '系统', status: 'pending', message: '正在选择参与 Agent...' },
      ...AGENT_STEPS.map(a => ({ id: a, agentName: a, status: 'pending' as const, message: `${a} 等待分析...` })),
      { id: 'fusion', agentName: 'ReportAgent', status: 'pending', message: '等待融合各 Agent 结论...' },
    ];
    setSteps(initSteps);

    // Step animation: animate through steps regardless of API speed
    const animate = async () => {
      const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
      await delay(400);
      setSteps(prev => prev.map(s => s.id === 'parse' ? { ...s, status: 'done', message: '事件信息解析完成' } : s.id === 'route' ? { ...s, status: 'thinking', message: '正在路由到相关 Agent...' } : s));
      await delay(400);
      setSteps(prev => prev.map(s => s.id === 'route' ? { ...s, status: 'done', message: `已选择 ${AGENT_STEPS.length} 个 Agent 参与研判` } : s));

      for (const agent of AGENT_STEPS) {
        setSteps(prev => prev.map(s => s.id === agent ? { ...s, status: 'thinking', message: `${agent} 正在分析...` } : s));
        await delay(500);
      }
    };

    // Phase 8: Try SSE stream, fallback to REST
    const body = { eventId: 'E_' + Date.now(), eventType: 'congestion', roadName: '人民路', direction: '东向西', avgSpeed: 8.0, queueLength: 300, duration: 900, weather: 'rain', timePeriod: 'morning_peak', isMainRoad: true, nearbyHospital: true };
    let streamFailed = false;

    const animatePromise = animate();
    const streamPromise = streamRoutedAnalyze(body, {
      onStep: (_stage, text) => {
        setSteps(prev => prev.map(s => s.status === 'thinking' ? { ...s, message: text } : s));
      },
      onAgentStart: (agentName) => {
        setSteps(prev => prev.map(s => s.id === agentName || s.id === 'fusion' ? { ...s, status: 'thinking', message: `${agentName} 正在分析...` } : s));
      },
      onAgentResult: (result) => {
        setSteps(prev => prev.map(s => s.agentName === result.agentName ? { ...s, status: 'done', message: `${s.agentName} 分析完成`, result } : s));
      },
      onConflictDone: (conflicts) => {
        setSteps(prev => prev.map(s => s.id === 'fusion' ? { ...s, message: `检测到 ${(conflicts as unknown[]).length} 个冲突` } : s));
      },
      onFusionDelta: (text) => { setSummary(prev => prev + text); },
      onFusionDone: () => { setSteps(prev => prev.map(s => s.id === 'fusion' ? { ...s, status: 'done', message: '融合决策生成完毕' } : s)); },
      onDone: () => { setSteps(prev => prev.map(s => ({ ...s, status: 'done' as const }))); },
      onError: () => { streamFailed = true; },
    });

    try { await Promise.all([streamPromise, animatePromise]); } catch { streamFailed = true; }

    // Fallback to REST if SSE failed
    if (streamFailed) {
      try {
        const r = await fetch('/api/agent/routed_analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const results = await r.json();
        const agentResults = (results.agentResults as Record<string,unknown>[]) || [];
        setSteps(prev => prev.map(s => {
          const ar = agentResults.find((a: Record<string,unknown>) => a.agentName === s.agentName);
          if (ar && AGENT_STEPS.includes(s.id)) return { ...s, status: 'done', message: `${s.agentName} 分析完成`, result: ar };
          if (s.id === 'fusion') return { ...s, status: 'done', message: '融合决策生成完毕', result: results };
          return { ...s, status: 'done' };
        }));
        setSummary(buildFusionSummary(results));
      } catch { /* both SSE and REST failed */ }
    }
    setLoading(false);
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>协同分析</h2>
      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 8px' }}>多Agent各自独立研判 → 逐步流式展示 → 冲突检测 → 融合处置建议</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <textarea value={input} onChange={e => setInput(e.target.value)} placeholder="输入事件描述..." rows={2} style={{ flex: 1, border: '1px solid #E5E7EB', borderRadius: 12, padding: '8px 12px', fontSize: 13, resize: 'none', fontFamily: 'inherit' }} />
        <button onClick={handleAnalyze} disabled={loading || !input.trim()} style={{ padding: '8px 16px', borderRadius: 12, border: 'none', background: loading ? '#E5E7EB' : '#0F766E', color: '#FFF', cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13, whiteSpace: 'nowrap' }}>{loading ? '分析中...' : '启动协同'}</button>
      </div>
      {steps.length > 0 && (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#6B7280', marginBottom: 4 }}>分析过程</div>
          {steps.map((s, i) => (
            <div key={s.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 12px', borderRadius: 10, background: s.status === 'thinking' ? '#FFF7E6' : s.status === 'done' ? '#F0FDFA' : '#F9FAFB', border: '1px solid #E5E7EB', opacity: s.status === 'pending' ? 0.5 : 1, transition: 'all 0.3s' }}>
              <div style={{ fontSize: 16, flexShrink: 0, width: 24, textAlign: 'center' }}>
                {s.status === 'thinking' ? '⏳' : s.status === 'done' ? '✅' : '○'}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: s.status === 'done' ? '#0F766E' : '#374151' }}>{s.agentName}</div>
                <div style={{ fontSize: 11, color: '#6B7280' }}>{s.message}</div>
                {s.result && s.id !== 'fusion' && AGENT_STEPS.includes(s.id) && (
                  <div style={{ marginTop: 4, fontSize: 11, color: '#374151' }}>
                    {(s.result.findings as string[] || []).map((f, j) => <div key={j} style={{ padding: '1px 0' }}>- {f}</div>)}
                    {String(s.result.suggestion || '') && <div style={{ color: '#0F766E', fontWeight: 600 }}>→ {String(s.result.suggestion || '')}</div>}
                  </div>
                )}
              </div>
            </div>
          ))}
          {summary && (
            <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #0F766E', borderLeft: '4px solid #0F766E', marginTop: 4 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#111827', marginBottom: 6 }}>融合决策</div>
              <div style={{ fontSize: 13, color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>{summary}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
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
