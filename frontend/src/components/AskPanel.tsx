/**
 * 交通知识问答面板 — RAG 问答
 */
import { useState } from 'react';
import { Card, Input, Button, Spin, Tag, Empty, message } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';

const API_BASE = '/api';

export default function AskPanel() {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Record<string,unknown>|null>(null);
  const [loading, setLoading] = useState(false);

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/rag/ask`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ question, limit: 5 }),
      });
      if (!res.ok) throw new Error('问答失败');
      setAnswer(await res.json());
    } catch (e) {
      message.error(String(e));
    } finally { setLoading(false); }
  };

  return (
    <Card
      title={<span><QuestionCircleOutlined style={{color:'#1677ff'}} /> 交通知识问答</span>}
      size="small"
      style={{ height:'100%', background:'rgba(16,20,52,0.85)', borderColor:'rgba(255,255,255,0.08)' }}
    >
      <Input.Search
        placeholder="问: 雨天早高峰主干道拥堵如何处置?"
        value={question}
        onChange={e => setQuestion(e.target.value)}
        onSearch={handleAsk}
        loading={loading}
        enterButton="提问"
      />
      <div style={{ marginTop:4, fontSize:11, color:'#666' }}>
        试试: 信号灯异常 / 事故应急 / 施工占道 / 行人闯入
      </div>

      {loading ? <Spin style={{ marginTop:16 }} /> : answer ? (
        <div style={{ marginTop:12, maxHeight:420, overflow:'auto' }}>
          <Tag color={answer.usedLLM ? 'green' : 'orange'}>
            {answer.usedLLM ? 'LLM 回答' : '模板回答'}
          </Tag>
          <pre style={{ whiteSpace:'pre-wrap', fontSize:12, color:'#ccc', marginTop:8 }}>
            {answer.answer as string}
          </pre>
          {(answer.evidence as unknown[] || []).length > 0 && (
            <div style={{ marginTop:8, fontSize:11, color:'#888' }}>
              检索到 {(answer.evidence as unknown[]).length} 条证据
            </div>
          )}
        </div>
      ) : <Empty description="输入问题开始问答" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
    </Card>
  );
}
