/**
 * 混合相似案例面板 — 规则 + 向量混合检索
 */
import { useState } from 'react';
import { Card, Button, Table, Tag, Spin, Empty, message } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';

const API_BASE = '/api';

export default function HybridSimilarityPanel({ eventId }: { eventId?: string }) {
  const [loading, setLoading] = useState(false);
  const [cases, setCases] = useState<Record<string,unknown>[]>([]);

  const handleSearch = async () => {
    if (!eventId) { message.warning('请先分析一个事件'); return; }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/similar_cases_hybrid/${eventId}?limit=5&min_score=0.3`);
      if (!res.ok) throw new Error('检索失败');
      const data = await res.json();
      setCases(data.similarCases || []);
    } catch (e) { message.error(String(e)); }
    finally { setLoading(false); }
  };

  const columns = [
    { title: 'ID', dataIndex: 'eventId', width: 120 },
    { title: '路段', dataIndex: 'roadName', ellipsis: true },
    {
      title: '规则', dataIndex: 'ruleSimilarity', width:60,
      render: (v: number) => <span style={{color:'#faad14'}}>{(v*100).toFixed(0)}%</span>,
    },
    {
      title: '向量', dataIndex: 'vectorSimilarity', width:60,
      render: (v: number) => <span style={{color:'#1677ff'}}>{(v*100).toFixed(0)}%</span>,
    },
    {
      title: '最终', dataIndex: 'finalSimilarity', width:60,
      render: (v: number) => <span style={{color:'#52c41a', fontWeight:'bold'}}>{(v*100).toFixed(0)}%</span>,
    },
    { title: '风险', dataIndex: 'riskLevel', width:70, render: (v:string) => <Tag>{v}</Tag> },
  ];

  return (
    <Card
      title={<span><ExperimentOutlined style={{color:'#1677ff'}} /> 混合相似检索 (规则+向量)</span>}
      size="small"
      extra={<Button size="small" onClick={handleSearch} loading={loading}>检索</Button>}
      style={{ height:'100%', background:'rgba(16,20,52,0.85)', borderColor:'rgba(255,255,255,0.08)' }}
    >
      {loading ? <Spin /> : cases.length === 0 ? <Empty description="点击检索" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
        <Table dataSource={cases as []} columns={columns} rowKey="eventId" size="small" pagination={false} scroll={{y:200}} />
      )}
    </Card>
  );
}
