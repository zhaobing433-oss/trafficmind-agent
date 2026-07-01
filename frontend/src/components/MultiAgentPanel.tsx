/**
 * 多 Agent 协同研判面板
 */
import { useState } from 'react';
import { Card, Button, Tag, Spin, Empty, message, Collapse } from 'antd';
import { TeamOutlined } from '@ant-design/icons';

const API_BASE = '/api';

const SAMPLE = {
  eventId: 'E'+Date.now(),
  eventType: 'congestion',
  roadName: '人民路-解放路路口',
  direction: '东向西',
  avgSpeed: 5.0, queueLength: 300, duration: 1200, vehicleCount: 150,
  weather: 'rain', timePeriod: 'morning_peak',
  isMainRoad: true, nearbySchool: false, nearbyHospital: true, confidence: 0.92,
};

const URG_COLORS: Record<string,string> = { critical:'magenta', high:'red', medium:'orange', low:'green' };

export default function MultiAgentPanel() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string,unknown>|null>(null);

  const handleAnalyze = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/agent/multi_analyze`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(SAMPLE),
      });
      if (!res.ok) throw new Error('研判失败');
      setResult(await res.json());
    } catch (e) { message.error(String(e)); }
    finally { setLoading(false); }
  };

  return (
    <Card
      title={<span><TeamOutlined style={{color:'#1677ff'}} /> 多 Agent 协同研判</span>}
      size="small"
      extra={<Button size="small" type="primary" onClick={handleAnalyze} loading={loading}>运行研判</Button>}
      style={{ height:'100%', background:'rgba(16,20,52,0.85)', borderColor:'rgba(255,255,255,0.08)' }}
    >
      {loading ? <Spin /> : !result ? <Empty description="点击运行多Agent协同研判" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
        <div style={{ maxHeight:480, overflow:'auto', fontSize:12 }}>
          <div style={{ marginBottom:8 }}>
            <Tag color="blue">{(result.eventSummary as Record<string,unknown>)?.eventType as string}</Tag>
            <Tag>{(result.eventSummary as Record<string,unknown>)?.riskLevel as string}</Tag>
            <Tag color={URG_COLORS[(result.dispatchPlan as Record<string,unknown>)?.urgency as string] || 'default'}>
              紧急度: {(result.dispatchPlan as Record<string,unknown>)?.urgency as string}
            </Tag>
          </div>
          <Collapse size="small" items={((result.agentResults as []) || []).map((a: Record<string,unknown>, i: number) => ({
            key: i,
            label: <span>{a.agentName as string} <Tag color={a.relevant ? 'green' : 'default'}>{a.relevant ? '参与' : '跳过'}</Tag></span>,
            children: (
              <div>
                {(a.findings as string[])?.map((f:string, j:number) => <div key={j} style={{padding:'2px 0'}}>- {f}</div>)}
                <div style={{marginTop:4, color:'#1677ff'}}>建议: {a.suggestion as string}</div>
              </div>
            ),
          }))} />
          <pre style={{ whiteSpace:'pre-wrap', fontSize:11, color:'#aaa', marginTop:8, maxHeight:200, overflow:'auto' }}>
            {result.report as string}
          </pre>
        </div>
      )}
    </Card>
  );
}
