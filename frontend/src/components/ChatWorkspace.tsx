/**
 * ChatWorkspace — 对话消息流 + 伪流式 + localStorage + ThinkingAvatar
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { thinkingSteps, streamText } from '../utils/stream';
import { formatAssistantAnswer } from '../utils/answerFormatter';
import {
  createConversation, saveConversation, loadConversation,
  buildContextualQuestion, generateConversationTitle, extractSummaryResult,
  type Conversation, type Message,
} from '../utils/conversation';
import { Spin, Tag, Collapse, Empty } from 'antd';
import { RobotOutlined, UserOutlined, WarningOutlined, SendOutlined, PlusOutlined } from '@ant-design/icons';
import ThinkingAvatar from './ThinkingAvatar';
import { chatApi, type ChatMessage as BackendMsg } from '../api/chatApi';

const API = '/api';
type R = Record<string, unknown>;

interface Props {
  initialPrompt?: string;
  initialMode?: string;
  conversationId?: string;
  sessionId?: string;  // backend session ID
  onConversationUpdate?: (conv?: Conversation) => void;
  onNewConversation?: () => void;
  showInput?: boolean;
  useBackend?: boolean; // Phase 6: use backend chat API
  title?: string;
  subtitle?: string;
  extraHeader?: React.ReactNode;
}

async function apiPost(path: string, body: unknown): Promise<R> {
  const r = await fetch(`${API}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
    throw new Error(err.detail || '请求失败 (' + r.status + ')');
  }
  return r.json();
}
async function apiGet(path: string): Promise<R> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

export default function ChatWorkspace({
  initialPrompt, initialMode, conversationId, sessionId, onConversationUpdate, onNewConversation,
  showInput = true, useBackend = true, title, subtitle, extraHeader,
}: Props) {
  const [conv, setConv] = useState<Conversation>(() => {
    if (conversationId) return loadConversation(conversationId) || createConversation('新对话', initialMode || 'react');
    return createConversation('新对话', initialMode || 'react');
  });
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState(initialMode || 'react');
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  const msgEnd = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load conversation when conversationId changes (legacy localStorage)
  useEffect(() => {
    if (!useBackend && conversationId) {
      const loaded = loadConversation(conversationId);
      if (loaded) setConv(loaded);
    }
  }, [conversationId]);

  // Load session from backend when sessionId changes (Phase 6)
  useEffect(() => {
    if (!useBackend || !sessionId) return;
    chatApi.getSession(sessionId).then(detail => {
      const msgs = (detail.messages || []).map((m: BackendMsg) => ({
        id: m.id, role: m.role as Message['role'], content: m.content, mode: m.mode,
        timestamp: new Date(m.created_at).getTime(), streaming: false,
      } as Message));
      setConv({
        id: sessionId, title: detail.session.title, mode: detail.session.mode,
        messages: msgs, createdAt: new Date(detail.session.created_at).getTime(),
        updatedAt: new Date(detail.session.updated_at).getTime(),
      });
    }).catch(() => {
      // Session may not exist yet
    });
  }, [sessionId]);

  // Handle initial prompt (only if conv is empty)
  useEffect(() => {
    if (initialPrompt && conv.messages.length === 0) {
      doSubmit(initialPrompt, initialMode || mode);
    }
  }, [initialPrompt]);

  useEffect(() => { onConversationUpdate?.(conv); }, [conv.id, conv.updatedAt]);
  useEffect(() => { msgEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [conv.messages, streamingMsgId]);

  const addMessage = useCallback((role: Message['role'], content: string, msgMode: string) => {
    const msg: Message = {
      id: 'msg_' + Date.now() + Math.random().toString(36).slice(2, 6),
      role, content, mode: msgMode, timestamp: Date.now(),
    };
    setConv(prev => {
      const updated = {
        ...prev,
        messages: [...prev.messages, msg],
        title: generateConversationTitle(prev.messages, role === 'user' ? content : prev.title),
      };
      saveConversation(updated);
      return updated;
    });
    return msg;
  }, []);

  const doSubmit = useCallback(async (text: string, submitMode: string) => {
    if (!text.trim() || loading) return;

    // Phase 6 backend mode
    if (useBackend) {
      addMessage('user', text.trim(), submitMode);
      setInput(''); setLoading(true);

      const skeletonId = 'msg_' + Date.now() + '_loading';
      setConv(prev => ({
        ...prev,
        messages: [...prev.messages, { id: skeletonId, role: 'assistant', mode: submitMode, content: '', timestamp: Date.now(), streaming: true } as Message],
      }));
      setStreamingMsgId(skeletonId);

      try {
        updateStreaming(skeletonId, thinkingSteps());

        // Ensure session exists
        let sid = sessionId;
        if (!sid) {
          const s = await chatApi.createSession(submitMode);
          sid = s.sessionId;
          setConv(prev => ({ ...prev, id: sid || prev.id }));
          onConversationUpdate?.();
        }

        const resp = await chatApi.sendMessage(sid, text.trim(), submitMode);

        // Build formatted answer
        const answerText = resp.assistantMessage.content || '';
        const abstainNote = resp.abstained ? '\n\n⚠ 依据不足，系统基于有限信息生成回答，可能存在不确定性。' : '';

        await streamText(skeletonId, answerText + abstainNote, (c) => updateStreaming(skeletonId, c));

        finalizeMessage(skeletonId, {
          answer: answerText, abstained: resp.abstained, confidence: resp.confidence,
          evidence: resp.evidence, warnings: resp.warnings,
          usedLLM: resp.assistantMessage.usedLLM,
        } as unknown as R);
      } catch (e) {
        const errMsg = e instanceof Error ? e.message : '请求失败';
        setConv(prev => ({ ...prev, messages: prev.messages.map(m => m.id === skeletonId ? { ...m, content: '❌ ' + errMsg, streaming: false } as Message : m) }));
        setStreamingMsgId(null);
      }
      finally { setLoading(false); }
      return;
    }

    // Legacy direct-call mode
    const question = buildContextualQuestion(conv, text.trim());
    addMessage('user', text.trim(), submitMode);
    setInput('');
    setLoading(true);

    const skeletonId = 'msg_' + Date.now() + '_loading';
    setConv(prev => ({
      ...prev,
      messages: [...prev.messages, { id: skeletonId, role: 'assistant', mode: submitMode, content: '', timestamp: Date.now(), streaming: true } as Message],
    }));
    setStreamingMsgId(skeletonId);

    try {
      let result: R | null = null;
      if (submitMode === 'react') {
        updateStreaming(skeletonId, thinkingSteps());
        result = await apiPost('/agent/react_diagnose', { question, max_steps: 3 });
        const formatted = formatAssistantAnswer('react', result, text);
        await streamText(skeletonId, formatted, (c) => updateStreaming(skeletonId, c));
      } else if (submitMode === 'routed') {
        updateStreaming(skeletonId, thinkingSteps());
        result = await apiPost('/agent/routed_analyze', { eventId: 'E_' + Date.now(), eventType: 'congestion', roadName: '人民路', direction: '东向西', avgSpeed: 8.0, queueLength: 180, duration: 600, weather: 'rain', timePeriod: 'morning_peak', isMainRoad: true });
        const formatted = formatAssistantAnswer('routed', result, text);
        await streamText(skeletonId, formatted, (c) => updateStreaming(skeletonId, c));
      } else if (submitMode === 'rag') {
        updateStreaming(skeletonId, thinkingSteps());
        result = await apiPost('/rag/ask', { question, limit: 5 });
        const formatted = formatAssistantAnswer('rag', result, text);
        await streamText(skeletonId, formatted, (c) => updateStreaming(skeletonId, c));
      } else if (submitMode === 'hybrid') {
        updateStreaming(skeletonId, '正在检索相似案例...');
        result = await apiGet('/similar_cases_hybrid/E202606300001?limit=5&min_score=0.3');
        const formatted = formatAssistantAnswer('hybrid', result, text);
        await streamText(skeletonId, formatted, (c) => updateStreaming(skeletonId, c));
      } else if (submitMode === 'report') {
        updateStreaming(skeletonId, '正在生成报告...');
        result = await apiGet('/reports/daily');
        const formatted = formatAssistantAnswer('report', result, text);
        await streamText(skeletonId, formatted, (c) => updateStreaming(skeletonId, c));
      } else {
        updateStreaming(skeletonId, thinkingSteps());
        result = await apiPost('/agent/react_diagnose', { question, max_steps: 3 });
        const formatted = formatAssistantAnswer('react', result, text);
        await streamText(skeletonId, formatted, (c) => updateStreaming(skeletonId, c));
      }

      finalizeMessage(skeletonId, result);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '请求失败';
      setConv(prev => ({
        ...prev,
        messages: prev.messages.map(m => m.id === skeletonId ? { ...m, content: '❌ ' + errMsg, streaming: false } as Message : m),
      }));
      setStreamingMsgId(null);
    } finally { setLoading(false); }
  }, [conv, loading]);

  function updateStreaming(id: string, content: string) {
    setConv(prev => ({
      ...prev,
      messages: prev.messages.map(m => m.id === id ? { ...m, content } as Message : m),
    }));
  }

  function finalizeMessage(id: string, result: R | null) {
    const summaryResult = result ? extractSummaryResult(result) : undefined;
    setConv(prev => ({
      ...prev,
      messages: prev.messages.map(m => {
        if (m.id !== id) return m;
        const content = (m as Message).content || '';
        return { ...m, content, streaming: false, summaryResult } as Message;
      }),
    }));
    saveConversation({ ...conv, messages: conv.messages });
    setStreamingMsgId(null);
  }

  const isStreaming = (msg: Message) => streamingMsgId === msg.id || (msg as Message & { streaming?: boolean }).streaming;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
      {(title || subtitle || extraHeader) && (
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            {title && <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: 0 }}>{title}</h2>}
            {subtitle && <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{subtitle}</p>}
            {extraHeader}
          </div>
          {onNewConversation && (
            <button onClick={onNewConversation} style={{ border: '1px solid #E5E7EB', borderRadius: 10, padding: '6px 14px', background: '#FFF', cursor: 'pointer', fontSize: 12, color: '#6B7280', whiteSpace: 'nowrap' }}>
              <PlusOutlined /> 新对话
            </button>
          )}
        </div>
      )}

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 16, minHeight: 200 }}>
        {conv.messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: 60, color: '#9CA3AF', fontSize: 14 }}>
            <RobotOutlined style={{ fontSize: 32, color: '#D1D5DB', marginBottom: 12 }} />
            <div>输入问题或点击场景卡片开始分析</div>
          </div>
        )}
        {conv.messages.map(msg => (
          <div key={msg.id} style={{
            display: 'flex', gap: 10, marginBottom: 16,
            flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
          }}>
            {/* Avatar */}
            <div style={{ flexShrink: 0 }}>
              {msg.role === 'user' ? (
                <div style={{ width: 36, height: 36, borderRadius: 18, background: '#E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <UserOutlined style={{ color: '#6B7280', fontSize: 14 }} />
                </div>
              ) : isStreaming(msg) ? (
                <ThinkingAvatar />
              ) : (
                <div style={{ width: 36, height: 36, borderRadius: 18, background: '#F0FDFA', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <RobotOutlined style={{ color: '#0F766E', fontSize: 16 }} />
                </div>
              )}
            </div>

            {/* Bubble */}
            <div style={{ flex: 1, minWidth: 0, maxWidth: msg.role === 'user' ? '70%' : '100%' }}>
              <div style={{
                fontSize: 11, color: '#9CA3AF', marginBottom: 2,
                textAlign: msg.role === 'user' ? 'right' : 'left',
              }}>
                {msg.role === 'user' ? '你' : 'TrafficMind'} · {new Date(msg.timestamp).toLocaleTimeString()}
                <Tag style={{ marginLeft: 6, fontSize: 10 }}>{msg.mode}</Tag>
              </div>
              <div style={{
                background: msg.role === 'user' ? '#0F766E' : '#FFF',
                color: msg.role === 'user' ? '#FFF' : '#111827',
                borderRadius: msg.role === 'user' ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
                padding: '12px 16px', fontSize: 13, lineHeight: 1.7,
                whiteSpace: 'pre-wrap',
                border: msg.role === 'assistant' ? '1px solid #E5E7EB' : 'none',
              }}>
                {isStreaming(msg) ? (msg.content || '▊') : (
                  msg.content.startsWith('❌') ? (
                    <div style={{ color: '#EF4444' }}>
                      <WarningOutlined style={{ marginRight: 6 }} />
                      {msg.content.replace('❌ ', '')}
                      <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>
                        请确认后端已启动 → http://127.0.0.1:8000/health
                      </div>
                    </div>
                  ) : msg.content
                )}
              </div>

              {/* Evidence / Debug collapsible */}
              {msg.role === 'assistant' && !isStreaming(msg) && msg.summaryResult && (
                <div style={{ marginTop: 4 }}>
                  <Collapse size="small" ghost items={[{
                    key: 'detail', label: <span style={{ fontSize: 11, color: '#9CA3AF' }}>查看详细依据</span>,
                    children: <DebugDetail summary={msg.summaryResult as unknown as Record<string,unknown>} />,
                  }]} />
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && !streamingMsgId && (
          <div style={{ textAlign: 'center', padding: 8 }}>
            <Spin size="small" /> <span style={{ fontSize: 12, color: '#9CA3AF' }}>TrafficMind 正在分析...</span>
          </div>
        )}
        <div ref={msgEnd} />
      </div>

      {/* Input */}
      {showInput && (
        <div style={{ background: '#FFF', borderRadius: 20, border: '1px solid #E5E7EB', padding: '8px 12px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)', marginTop: 8 }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
            {(['react', 'routed', 'rag', 'hybrid', 'report'] as const).map(k => (
              <button key={k} onClick={() => setMode(k)}
                style={{ border: 'none', borderRadius: 20, padding: '4px 12px', fontSize: 12, cursor: 'pointer', background: mode === k ? '#F0FDFA' : '#F9FAFB', color: mode === k ? '#0F766E' : '#6B7280', fontWeight: mode === k ? 600 : 400 }}>
                {{ react: '🤖 智能诊断', routed: '🔍 事件研判', rag: '📖 知识问答', hybrid: '📊 相似案例', report: '📋 报告生成' }[k]}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSubmit(input, mode); } }}
              placeholder="输入问题或点击场景卡片..." rows={2}
              style={{ flex: 1, border: 'none', outline: 'none', resize: 'none', fontSize: 14, color: '#111827', background: 'transparent', fontFamily: 'inherit', lineHeight: 1.5 }} />
            <button onClick={() => doSubmit(input, mode)}
              disabled={loading || !input.trim()}
              style={{ width: 40, height: 40, borderRadius: 20, border: 'none', background: loading || !input.trim() ? '#E5E7EB' : '#0F766E', color: '#FFF', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, flexShrink: 0 }}>
              <SendOutlined />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DebugDetail({ summary }: { summary: Record<string, unknown> }) {
  const s = summary as Record<string, unknown>;
  const usedLLM = s.usedLLM as boolean | undefined;
  const confidence = s.confidence as number | undefined;
  const evidenceCount = s.evidenceCount as number | undefined;
  const agentsCount = s.agentsCount as number | undefined;
  const conflictsCount = s.conflictsCount as number | undefined;
  const casesCount = s.casesCount as number | undefined;
  const urgency = s.urgency as string | undefined;
  return (
    <div style={{ fontSize: 11, color: '#6B7280', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {usedLLM !== undefined && <Tag color={usedLLM ? 'green' : 'default'}>{usedLLM ? 'LLM回答' : '模板回答'}</Tag>}
      {confidence != null && <Tag>置信度: {confidence}</Tag>}
      {evidenceCount != null && evidenceCount > 0 && <Tag color="blue">{evidenceCount}条证据</Tag>}
      {agentsCount != null && agentsCount > 0 && <Tag color="cyan">{agentsCount}个Agent</Tag>}
      {conflictsCount != null && conflictsCount > 0 && <Tag color="red">{conflictsCount}个冲突</Tag>}
      {casesCount != null && casesCount > 0 && <Tag color="purple">{casesCount}个案例</Tag>}
      {urgency && <Tag color="orange">紧急度: {urgency}</Tag>}
    </div>
  );
}
