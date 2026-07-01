/**
 * RAG 知识库面板 — 向量库状态 + 语义检索
 */
import { useState, useEffect } from 'react';
import { Card, Button, Input, Table, Tag, Spin, Empty, message, Space } from 'antd';
import { SearchOutlined, ReloadOutlined, BuildOutlined } from '@ant-design/icons';

const API_BASE = '/api';

async function apiGet(path: string) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error((await res.json().catch(()=>({detail:'error'}))).detail);
  return res.json();
}
async function apiPost(path: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST', headers: body ? {'Content-Type':'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error((await res.json().catch(()=>({detail:'error'}))).detail);
  return res.json();
}

export default function RagPanel() {
  const [status, setStatus] = useState<Record<string,unknown>>({});
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Record<string,unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const fetchStatus = async () => {
    try { setStatus(await apiGet('/rag/status')); } catch { /* ignore */ }
  };
  useEffect(() => { fetchStatus(); }, []);

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      const r = await apiPost('/rag/rebuild_index');
      message.success(r.message || '索引重建完成');
      fetchStatus();
    } catch (e) { message.error(String(e)); }
    finally { setRebuilding(false); }
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const r = await apiGet(`/rag/search?query=${encodeURIComponent(query)}&limit=5`);
      setResults(r.results || []);
    } catch { setResults([]); }
    finally { setLoading(false); }
  };

  return (
    <Card
      title="RAG 知识库检索" size="small"
      extra={
        <Space>
          <Button size="small" icon={<BuildOutlined />} loading={rebuilding} onClick={handleRebuild}>重建索引</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={fetchStatus}>刷新</Button>
        </Space>
      }
      style={{ height:'100%', background:'rgba(16,20,52,0.85)', borderColor:'rgba(255,255,255,0.08)' }}
    >
      <div style={{ marginBottom:8, fontSize:12, color:'#888' }}>
        {status.enabled ? `已启用 | ${status.documentCount || 0} 条文档 | ${status.embeddingMode || ''}` : '向量库未启用'}
      </div>
      <Input.Search
        placeholder="输入查询: 拥堵处置、信号灯异常..."
        value={query}
        onChange={e => setQuery(e.target.value)}
        onSearch={handleSearch}
        loading={loading}
        style={{ marginBottom:8 }}
      />
      {loading ? <Spin /> : results.length === 0 ? <Empty description="输入关键词检索" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
        <div style={{ maxHeight:300, overflow:'auto' }}>
          {results.map((r, i) => (
            <div key={i} style={{ marginBottom:8, padding:8, background:'rgba(0,0,0,0.2)', borderRadius:4, fontSize:12 }}>
              <div style={{ display:'flex', gap:8, marginBottom:4 }}>
                <Tag color="blue">{r.docType as string}</Tag>
                {(r.score as number) > 0 && <Tag>{(r.score as number).toFixed(2)}</Tag>}
              </div>
              <div style={{ color:'#ccc' }}>{(r.content as string)?.slice(0,150)}...</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
