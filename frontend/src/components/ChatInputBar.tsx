/**
 * ChatInputBar — 底部 AI 输入框 + 模式选择
 */
import { useState } from 'react';
import { SendOutlined } from '@ant-design/icons';

const MODES = [
  { key: 'react', label: '智能诊断', icon: '🤖' },
  { key: 'routed', label: '事件研判', icon: '🔍' },
  { key: 'rag', label: '知识问答', icon: '📖' },
  { key: 'hybrid', label: '相似案例', icon: '📊' },
  { key: 'report', label: '报告生成', icon: '📋' },
];

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (text: string, mode: string) => void;
  loading?: boolean;
}

export default function ChatInputBar({ value, onChange, onSubmit, loading }: Props) {
  const [mode, setMode] = useState('react');

  const handleSubmit = () => {
    const text = value.trim();
    if (!text || loading) return;
    onSubmit(text, mode);
  };

  return (
    <div style={{
      background: '#FFF', borderRadius: 20, border: '1px solid #E5E7EB',
      padding: '8px 12px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
    }}>
      {/* Mode selector */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
        {MODES.map(m => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            style={{
              border: 'none', borderRadius: 20, padding: '4px 12px',
              fontSize: 12, cursor: 'pointer',
              background: mode === m.key ? '#F0FDFA' : '#F9FAFB',
              color: mode === m.key ? '#0F766E' : '#6B7280',
              fontWeight: mode === m.key ? 600 : 400,
              transition: 'all 0.15s',
            }}
          >
            {m.icon} {m.label}
          </button>
        ))}
      </div>

      {/* Input row */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <textarea
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="输入问题或点击上方场景卡片自动填充..."
          rows={2}
          style={{
            flex: 1, border: 'none', outline: 'none', resize: 'none',
            fontSize: 14, color: '#111827', background: 'transparent',
            fontFamily: 'inherit', lineHeight: 1.5,
          }}
        />
        <button
          onClick={handleSubmit}
          disabled={loading || !value.trim()}
          style={{
            width: 40, height: 40, borderRadius: 20, border: 'none',
            background: loading || !value.trim() ? '#E5E7EB' : '#0F766E',
            color: '#FFF', cursor: loading || !value.trim() ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, flexShrink: 0,
            transition: 'background 0.15s',
          }}
        >
          <SendOutlined />
        </button>
      </div>
    </div>
  );
}
