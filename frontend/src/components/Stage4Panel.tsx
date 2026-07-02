/**
 * Stage4Panel — Phase 4: Controlled Agent Collaboration
 * Includes: ReAct Diagnose + Routed Analyze + Conflicts + Event Chain
 */
import { useState } from 'react';
import { Card, Input, Button, Tag, Spin, Collapse, Empty, message, Space } from 'antd';
import { RobotOutlined, ApartmentOutlined, AlertOutlined, LinkOutlined } from '@ant-design/icons';

const API = '/api';

async function apiPost(path: string, body: unknown) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({ detail: 'error' }))).detail);
  return res.json();
}

const SAMPLE_EVENT = {
  eventId: 'E' + Date.now(), eventType: 'congestion', roadName: '人民路-解放路路口',
  direction: '东向西', avgSpeed: 5.0, queueLength: 300, duration: 1200,
  weather: 'rain', timePeriod: 'morning_peak', isMainRoad: true,
  nearbySchool: false, nearbyHospital: true, confidence: 0.92,
};

const URG_COLORS: Record<string, string> = { critical: 'magenta', high: 'red', medium: 'orange', low: 'green' };

export default function Stage4Panel() {
  // ReAct
  const [reactQ, setReactQ] = useState('人民路最近为什么高风险事件多？');
  const [reactLoading, setReactLoading] = useState(false);
  const [reactResult, setReactResult] = useState<Record<string, unknown> | null>(null);

  // Routed
  const [routedLoading, setRoutedLoading] = useState(false);
  const [routedResult, setRoutedResult] = useState<Record<string, unknown> | null>(null);

  const handleReact = async () => {
    setReactLoading(true);
    try { setReactResult(await apiPost('/agent/react_diagnose', { question: reactQ, max_steps: 3 })); }
    catch (e) { message.error(String(e)); }
    finally { setReactLoading(false); }
  };

  const handleRouted = async () => {
    setRoutedLoading(true);
    try { setRoutedResult(await apiPost('/agent/routed_analyze', SAMPLE_EVENT)); }
    catch (e) { message.error(String(e)); }
    finally { setRoutedLoading(false); }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* ReAct Diagnose */}
      <Card
        size="small" title={<span><RobotOutlined style={{ color: '#1677ff' }} /> ReAct 诊断分析</span>}
        extra={<Button size="small" type="primary" onClick={handleReact} loading={reactLoading}>诊断</Button>}
        style={{ background: 'rgba(16,20,52,0.85)', borderColor: 'rgba(255,255,255,0.08)' }}
      >
        <Input.TextArea value={reactQ} onChange={e => setReactQ(e.target.value)} rows={2}
          placeholder="输入诊断问题..." style={{ marginBottom: 8, fontSize: 12 }} />
        {reactLoading ? <Spin /> : reactResult ? (
          <div style={{ maxHeight: 370, overflow: 'auto', fontSize: 12 }}>
            <Tag color="blue">{reactResult.usedLLM ? 'LLM' : 'Rule'}</Tag>
            <span style={{ color: '#888' }}> {String(reactResult.confidence ?? 0)} confidence</span>
            <div style={{ margin: '8px 0', whiteSpace: 'pre-wrap', color: '#ccc' }}>
              {String(reactResult.finalAnswer ?? '')}
            </div>
            {(reactResult.warnings as string[])?.map((w, i) => (
              <div key={i} style={{ color: '#faad14', fontSize: 11 }}>⚠ {w}</div>
            ))}
          </div>
        ) : <Empty description="点击诊断" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>

      {/* Routed Analyze */}
      <Card
        size="small" title={<span><ApartmentOutlined style={{ color: '#1677ff' }} /> 动态路由协同研判</span>}
        extra={<Button size="small" type="primary" onClick={handleRouted} loading={routedLoading}>研判</Button>}
        style={{ background: 'rgba(16,20,52,0.85)', borderColor: 'rgba(255,255,255,0.08)' }}
      >
        {routedLoading ? <Spin /> : routedResult ? (
          <div style={{ maxHeight: 370, overflow: 'auto', fontSize: 12 }}>
            {/* Agents */}
            <div style={{ marginBottom: 6 }}>
              {(routedResult.selectedAgents as string[])?.map(a => <Tag key={a} color="blue">{a}</Tag>)}
              <Tag color={URG_COLORS[(routedResult.dispatchPlan as Record<string, unknown>)?.urgency as string] || 'default'}>
                {String((routedResult.dispatchPlan as Record<string, unknown>)?.urgency ?? '')}
              </Tag>
            </div>
            {/* Routing reasons */}
            <div style={{ color: '#888', marginBottom: 8 }}>
              {(routedResult.routingReasons as string[])?.slice(0, 3).map((r, i) => <div key={i}>* {r}</div>)}
            </div>
            {/* Conflicts */}
            {((routedResult.conflicts as unknown[])?.length ?? 0) > 0 && (
              <div style={{ background: 'rgba(255,77,79,0.15)', padding: 6, borderRadius: 4, marginBottom: 6 }}>
                <AlertOutlined style={{ color: '#ff4d4f' }} /> {(routedResult.conflicts as unknown[]).length} conflicts detected
                {(routedResult.conflicts as Record<string, unknown>[])?.map((c, i) => (
                  <div key={i} style={{ color: '#ff7875', fontSize: 11 }}>
                    [{c.severity as string}] {c.description as string}
                  </div>
                ))}
              </div>
            )}
            {/* Event Chain */}
            <div style={{ marginBottom: 6 }}>
              <LinkOutlined style={{ color: '#52c41a' }} /> Chain:
              {((routedResult.eventChain as Record<string, unknown>)?.triggeredAgents as string[])?.join(', ') || 'none'}
            </div>
            {/* Resolved Plan */}
            <div style={{ fontSize: 11, color: '#52c41a', marginTop: 6 }}>
              resolvedPlan: urgency={String((routedResult.resolvedPlan as Record<string,unknown>)?.urgency ?? 'N/A')},
              resolved={String((routedResult.resolvedPlan as Record<string,unknown>)?.resolved ?? 'N/A')}
            </div>
            {/* Final Decision */}
            <div style={{ whiteSpace: 'pre-wrap', color: '#ccc', padding: 6, background: 'rgba(0,0,0,0.2)', borderRadius: 4 }}>
              {String(routedResult.finalDecision ?? '')}
            </div>
          </div>
        ) : <Empty description="点击研判" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>
    </div>
  );
}
