import { useState, useCallback, useEffect } from 'react';
import LayoutShell from './components/LayoutShell';
import HomeHero from './components/HomeHero';
import ScenarioGrid from './components/ScenarioGrid';
import ChatWorkspace from './components/ChatWorkspace';
import { chatApi, type SessionItem } from './api/chatApi';

const VIEW_MODE: Record<string, string> = {
  home: 'react', analyze: 'routed', qa: 'rag', similar: 'hybrid',
  multi: 'routed', report: 'report', alert: 'react', guide: 'react',
};

export default function App() {
  const [view, setView] = useState('home');
  const [activePrompt, setActivePrompt] = useState<string | undefined>();
  const [activeMode, setActiveMode] = useState('react');
  const [convId, setConvId] = useState<string | undefined>();
  const [recentRefresh, setRecentRefresh] = useState(0);
  const [sessions, setSessions] = useState<SessionItem[]>([]);

  // Load sessions from backend
  useEffect(() => {
    chatApi.listSessions(30).then(setSessions).catch(() => {});
  }, [recentRefresh]);

  const handleConversationUpdate = useCallback(() => {
    setRecentRefresh(Date.now());
  }, []);

  const handleNewConversation = async () => {
    try {
      const s = await chatApi.createSession('react');
      setConvId(s.sessionId);
      setView('home'); setActiveMode('react'); setActivePrompt(undefined);
      setRecentRefresh(Date.now());
    } catch { /* backend not available, fall through */ }
  };

  const handleScenario = (prompt: string) => {
    setView('home'); setActiveMode('react');
    setActivePrompt(prompt); setConvId(undefined);
  };

  const handleNavigate = (v: string) => {
    setView(v); setActiveMode(VIEW_MODE[v] || 'react'); setActivePrompt(undefined);
  };

  const handleRecentClick = (id: string, mode: string) => {
    setView('home'); setActiveMode(mode); setActivePrompt(undefined); setConvId(id);
  };

  const handleDeleteSession = async (id: string) => {
    try { await chatApi.deleteSession(id); setRecentRefresh(Date.now()); if (convId === id) setConvId(undefined); }
    catch { /* ignore */ }
  };

  const recentItems = sessions.map(s => ({ id: s.id, title: s.title, mode: s.mode, updatedAt: new Date(s.updated_at).getTime() }));

  const renderContent = () => {
    if (view === 'home' || view === 'qa') {
      return (
        <>
          {view === 'home' && <HomeHero />}
          {view === 'home' && <ScenarioGrid onSelect={handleScenario} />}
          <div style={{ marginTop: view === 'home' ? 24 : 0 }}>
            <ChatWorkspace
              key={convId || 'new'}
              initialPrompt={activePrompt}
              initialMode={activeMode}
              sessionId={convId}
              onConversationUpdate={handleConversationUpdate}
              onNewConversation={handleNewConversation}
              useBackend={true}
              title={view === 'qa' ? '知识问答' : undefined}
              subtitle={view === 'qa' ? '基于 RAG 交通知识库检索和可信回答' : undefined}
              extraHeader={view === 'qa' ? (
                <button onClick={async () => { try { await fetch('/api/rag/rebuild_index', { method: 'POST' }); alert('索引重建完成'); } catch { alert('重建失败'); } }}
                  style={{ padding: '4px 12px', borderRadius: 8, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12, marginTop: 8 }}>
                  🔄 重建 RAG 索引
                </button>
              ) : undefined}
            />
          </div>
        </>
      );
    }

    const views: Record<string, () => React.ReactNode> = {
      analyze: () => <ChatWorkspace key={convId || 'analyze'} sessionId={convId} initialMode="routed" useBackend={true} onConversationUpdate={handleConversationUpdate} onNewConversation={handleNewConversation} title="事件研判" subtitle="动态路由多 Agent 协同研判" />,
      similar: () => (
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827' }}>相似案例检索</h2>
          <p style={{ fontSize: 13, color: '#9CA3AF', marginBottom: 16 }}>混合相似度 = 规则相似度 × 0.6 + 向量语义相似度 × 0.4</p>
          <ChatWorkspace key={convId || 'similar'} sessionId={convId} initialMode="hybrid" useBackend={true} onConversationUpdate={handleConversationUpdate} onNewConversation={handleNewConversation} showInput={false} />
        </div>
      ),
      multi: () => <ChatWorkspace key={convId || 'multi'} sessionId={convId} initialMode="routed" useBackend={true} onConversationUpdate={handleConversationUpdate} onNewConversation={handleNewConversation} title="协同分析" subtitle="多 Agent 协同研判" />,
      report: () => <ChatWorkspace key={convId || 'report'} sessionId={convId} initialMode="report" useBackend={true} onConversationUpdate={handleConversationUpdate} onNewConversation={handleNewConversation} title="统计报告" />,
      alert: () => <AlertDashboard />,
      guide: () => <GuidePage />,
    };
    const v = views[view];
    return v ? v() : null;
  };

  return (
    <LayoutShell activeView={view} onNavigate={handleNavigate} onRecentClick={handleRecentClick}
      onNewConversation={handleNewConversation} activeConvId={convId} recentList={recentItems}>
      <div style={{ maxWidth: 960, margin: '0 auto', width: '100%', padding: '0 24px 32px' }}>
        {renderContent()}
        <div style={{ textAlign: 'center', padding: '24px 0 12px', fontSize: 11, color: '#D1D5DB' }}>
          TrafficMind Agent · Phase 6 · 业务级会话持久化 + 可信RAG
        </div>
      </div>
    </LayoutShell>
  );
}

function QuickEventSelector({ onSelect }: { onSelect: (eid: string) => void }) {
  const [events, setEvents] = useState<{ eventId: string; eventTypeCn: string; roadName: string }[]>([]);
  useEffect(() => { fetch('/api/history?limit=10').then(r => r.json()).then(d => setEvents(d.records || [])).catch(() => {}); }, []);
  if (events.length === 0) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 8 }}>从历史事件中选择：</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {events.slice(0, 8).map(e => (
          <button key={e.eventId} onClick={() => onSelect(e.eventId)} style={{ padding: '4px 10px', borderRadius: 8, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12 }}>{e.eventId}</button>
        ))}
      </div>
    </div>
  );
}

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
        <h3 style={{ fontSize: 15, fontWeight: 600, color: '#EF4444' }}>未闭环事件 ({alerts.length})</h3>
        {(alerts as Record<string,unknown>[]).slice(0, 10).map((a, i) => (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #F3F4F6', fontSize: 12 }}>
            <strong>{String(a.eventId)}</strong> {String(a.eventType)} · {String(a.roadName)} · {String(a.riskLevel)}
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

function GuidePage() {
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ background: '#FFF', borderRadius: 16, padding: 16, border: '1px solid #E5E7EB' }}>
        <h3 style={{ fontSize: 15, fontWeight: 600 }}>系统能力</h3>
        <div style={{ fontSize: 13, color: '#4B5563', lineHeight: 1.8 }}>
          <p>✅ 业务级会话持久化（SQLite）</p>
          <p>✅ 可信 RAG（召回→重排→阈值→拒答）</p>
          <p>✅ 上下文记忆管理（短期+长期摘要）</p>
          <p>✅ DeepSeek LLM 可选接入</p>
          <p>🔜 流式 SSE 回答</p>
        </div>
      </div>
    </div>
  );
}
