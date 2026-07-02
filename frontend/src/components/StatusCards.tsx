/**
 * StatusCards — 顶部 4 个轻量状态卡片
 * 调用 /stats /alerts/unclosed /rag/status
 */
import { useState, useEffect } from 'react';

interface Stats { totalEvents: number; highRiskCount: number; }
interface Alerts { count: number; }
interface RagStatus { documentCount: number; }

const API = '/api';

async function fetchSafe<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`${API}${path}`);
    if (!r.ok) return fallback;
    return await r.json();
  } catch { return fallback; }
}

export default function StatusCards() {
  const [stats, setStats] = useState<Stats>({ totalEvents: 0, highRiskCount: 0 });
  const [alerts, setAlerts] = useState<Alerts>({ count: 0 });
  const [rag, setRag] = useState<RagStatus>({ documentCount: 0 });

  useEffect(() => {
    fetchSafe<Stats>('/stats', { totalEvents: 0, highRiskCount: 0 }).then(setStats);
    fetchSafe<Alerts>('/alerts/unclosed?hours=720', { count: 0 }).then(setAlerts);
    fetchSafe<RagStatus>('/rag/status', { documentCount: 0 }).then(setRag);
  }, []);

  const cards = [
    { label: '今日事件数', value: stats.totalEvents, color: '#0F766E' },
    { label: '高风险事件', value: stats.highRiskCount, color: '#EF4444' },
    { label: '未闭环事件', value: alerts.count, color: '#F59E0B' },
    { label: 'RAG 文档数', value: rag.documentCount, color: '#3B82F6' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
      {cards.map(c => (
        <div key={c.label} style={{
          background: '#FFF', borderRadius: 16, padding: '16px 20px',
          border: '1px solid #E5E7EB', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
          <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 4 }}>{c.label}</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: c.color }}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}
