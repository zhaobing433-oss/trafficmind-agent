/**
 * ResultWorkspace — 结果工作区
 * 根据 mode 调用不同 API，Tab 展示结果
 */
import { useState, useEffect } from 'react';
import { Spin, Tag, Empty, Tabs } from 'antd';
import {
  SafetyOutlined, BookOutlined, ApartmentOutlined,
  AlertOutlined, FileTextOutlined, ExperimentOutlined,
} from '@ant-design/icons';

const API = '/api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type R = Record<string, any>;

interface Props { text: string; mode: string; onDone?: () => void; }

async function post(path: string, body: unknown) {
  const r = await fetch(`${API}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function get(path: string) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export default function ResultWorkspace({ text, mode, onDone }: Props) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<R | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!text) return;
    let cancelled = false;
    setLoading(true); setError(''); setResult(null);
    (async () => {
      try {
        let r: R | null = null;
        if (mode === 'react') r = await post('/agent/react_diagnose', { question: text, max_steps: 3 });
        else if (mode === 'routed') r = await post('/agent/routed_analyze', { eventId: 'E_' + Date.now(), eventType: 'congestion', roadName: '人民路', direction: '东向西', avgSpeed: 8.0, queueLength: 180, duration: 600, weather: 'rain', timePeriod: 'morning_peak', isMainRoad: true });
        else if (mode === 'rag') r = await post('/rag/ask', { question: text, limit: 5 });
        else if (mode === 'hybrid') r = await get('/similar_cases_hybrid/E202606300001?limit=5&min_score=0.3');
        else if (mode === 'report') r = await get('/reports/daily');
        if (!cancelled) { setResult(r); onDone?.(); }
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : '请求失败'); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [text, mode]);

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><Spin size="large" /></div>;
  if (error) return <div style={{ padding: 40, textAlign: 'center', color: '#EF4444' }}>{error}</div>;
  if (!result) return <Empty description="输入问题开始分析" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const items: R[] = [];

  if (result.steps || result.finalAnswer) {
    items.push({
      key: 'diagnosis', label: <span><SafetyOutlined /> 研判结果</span>,
      children: (
        <div style={{ fontSize: 13 }}>
          {result.finalAnswer && (
            <div style={{ whiteSpace: 'pre-wrap', color: '#111827', background: '#F0FDFA', padding: 12, borderRadius: 12, marginBottom: 12, borderLeft: '3px solid #0F766E' }}>
              {String(result.finalAnswer)}
            </div>
          )}
          {(result.steps as R[]).map((s: R, i: number) => (
            <div key={i} style={{ fontSize: 12, color: '#6B7280', marginBottom: 4 }}>
              Step {String(s.step)}: {String(s.action)} &rarr; {String(s.observation ?? '').slice(0, 80)}...
            </div>
          ))}
          {(result.warnings as string[] || []).map((w: string, i: number) => (
            <Tag color="warning" key={i} style={{ fontSize: 11 }}>{w}</Tag>
          ))}
        </div>
      ),
    });
  }

  if (result.evidence || result.answer) {
    items.push({
      key: 'rag', label: <span><BookOutlined /> RAG 依据</span>,
      children: (
        <div style={{ fontSize: 13 }}>
          {result.answer && <div style={{ whiteSpace: 'pre-wrap', color: '#111827', marginBottom: 12, lineHeight: 1.7 }}>{String(result.answer)}</div>}
          {(result.evidence as R[] || []).map((e: R, i: number) => (
            <div key={i} style={{ padding: 8, marginBottom: 6, borderRadius: 8, background: '#F9FAFB', border: '1px solid #E5E7EB', fontSize: 12 }}>
              <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
                <Tag color="blue" style={{ fontSize: 10 }}>{String(e.docType ?? '')}</Tag>
                <span style={{ color: '#9CA3AF' }}>score: {Number(e.score ?? 0).toFixed(2)}</span>
              </div>
              <div style={{ color: '#4B5563' }}>{String(e.content ?? '').slice(0, 200)}...</div>
            </div>
          ))}
        </div>
      ),
    });
  }

  if (result.agentResults || result.selectedAgents) {
    items.push({
      key: 'agents', label: <span><ApartmentOutlined /> 协同分析</span>,
      children: (
        <div style={{ fontSize: 13 }}>
          {(result.selectedAgents as string[] || []).map((a: string) => <Tag key={a} color="cyan">{a}</Tag>)}
          <div style={{ marginTop: 8 }}>
            {(result.routingReasons as string[] || []).map((r: string, i: number) => (
              <div key={i} style={{ color: '#6B7280', fontSize: 12 }}>&bull; {r}</div>
            ))}
          </div>
          {(result.agentResults as R[] || []).map((a: R, i: number) => (
            <div key={i} style={{ padding: 8, marginTop: 6, borderRadius: 8, background: '#F9FAFB', border: '1px solid #E5E7EB', fontSize: 12 }}>
              <strong>{String(a.agentName ?? '')}</strong> <Tag color="green">{String(a.urgency ?? '')}</Tag>
              {(a.findings as string[] || []).map((f: string, j: number) => <div key={j}>- {f}</div>)}
              <div style={{ color: '#0F766E', marginTop: 4 }}>{String(a.suggestion ?? '')}</div>
            </div>
          ))}
        </div>
      ),
    });
  }

  if (result.conflicts && (result.conflicts as R[]).length > 0) {
    items.push({
      key: 'conflicts', label: <span><AlertOutlined /> 冲突检测 ({(result.conflicts as R[]).length})</span>,
      children: (
        <div style={{ fontSize: 13 }}>
          {(result.conflicts as R[]).map((c: R, i: number) => (
            <div key={i} style={{ padding: 10, marginBottom: 8, borderRadius: 12, background: '#FEF2F2', borderLeft: '3px solid #EF4444' }}>
              <Tag color="red">{String(c.severity ?? '')}</Tag>
              <div style={{ fontWeight: 600, margin: '4px 0' }}>{String(c.description ?? '')}</div>
              <div style={{ color: '#0F766E' }}>&rarr; {String(c.resolution ?? '')}</div>
            </div>
          ))}
          {result.resolvedPlan && (
            <div style={{ marginTop: 8, padding: 8, background: '#F0FDFA', borderRadius: 8, fontSize: 12 }}>
              urgency: {String((result.resolvedPlan as R).urgency ?? '')}
            </div>
          )}
        </div>
      ),
    });
  }

  if (result.similarCases) {
    items.push({
      key: 'similar', label: <span><ExperimentOutlined /> 相似案例 ({(result.similarCases as R[]).length ?? 0})</span>,
      children: (
        <div style={{ fontSize: 13 }}>
          {(result.similarCases as R[]).map((c: R, i: number) => (
            <div key={i} style={{ padding: 8, marginBottom: 6, borderRadius: 8, background: '#F9FAFB', border: '1px solid #E5E7EB' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontWeight: 600 }}>{String(c.eventId ?? '')}</span>
                <Tag>{String(c.eventType ?? '')}</Tag>
                <span style={{ color: '#0F766E', fontWeight: 600 }}>{(Number(c.finalSimilarity ?? c.similarityScore ?? 0) * 100).toFixed(0)}%</span>
              </div>
              <div style={{ color: '#6B7280' }}>{String(c.roadName ?? '')}</div>
            </div>
          ))}
        </div>
      ),
    });
  }

  if (result.report || result.reportText) {
    items.push({
      key: 'report', label: <span><FileTextOutlined /> 报告摘要</span>,
      children: (
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: '#4B5563', background: '#F9FAFB', padding: 12, borderRadius: 12, border: '1px solid #E5E7EB', maxHeight: 400, overflow: 'auto' }}>
          {String(result.reportText ?? result.report ?? '')}
        </pre>
      ),
    });
  }

  return (
    <div style={{ background: '#FFF', borderRadius: 20, border: '1px solid #E5E7EB', padding: 16 }}>
      <Tabs size="small" items={items as never} />
    </div>
  );
}
