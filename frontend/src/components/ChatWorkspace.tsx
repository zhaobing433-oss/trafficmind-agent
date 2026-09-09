/**
 * ChatWorkspace — 对话消息流 + 后端 API + 伪流式
 * Phase 7: onSessionCreated 修复追问创建新session的bug
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { flushSync } from 'react-dom';
import { streamText } from '../utils/stream';
import { createConversation, loadConversation, type Conversation, type Message } from '../utils/conversation';
import { chatApi, type ChatMessage as BackendMsg } from '../api/chatApi';
import { streamChat } from '../api/streamApi';
import { Spin, Tag, Collapse } from 'antd';
import { RobotOutlined, UserOutlined, WarningOutlined, SendOutlined, PlusOutlined } from '@ant-design/icons';
import ThinkingAvatar from './ThinkingAvatar';
import RagTracePanel from './rag/RagTracePanel';
import { RelatedWorkflowRuns } from './workflow/RelatedWorkflowRuns';
import type { RagEvidenceItem } from '../types/ragV2';

type R = Record<string, unknown>;

interface Props {
  sessionId?: string;
  pendingCreate?: boolean;
  draftInput?: string;
  draftMode?: string;
  onDraftConsumed?: () => void;
  defaultMode?: string;
  showFullModes?: boolean;
  onSessionCreated?: (sessionId: string) => void;  // CRITICAL: tells App the new session ID
  onConversationUpdate?: () => void;
  onNewConversation?: () => void;
  onOpenWorkflowRun?: (runId: string) => void;
  view?: string;
}

export default function ChatWorkspace({
  sessionId, pendingCreate, draftInput, draftMode, onDraftConsumed,
  defaultMode = 'react', showFullModes = true, onSessionCreated,
  onConversationUpdate, onNewConversation, onOpenWorkflowRun, view = 'home',
}: Props) {
  const [conv, setConv] = useState<Conversation>(() =>
    loadConversation(sessionId || '') || createConversation('新对话', defaultMode));
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState(defaultMode);
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  // Track whether WE (this component instance) have already created a session.
  // This prevents re-creating on re-renders.
  const [hasCreatedSession, setHasCreatedSession] = useState(false);
  const msgEnd = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load from backend when sessionId changes (e.g., clicked recent analysis)
  // CRITICAL: Do NOT overwrite local streaming messages from a just-created session
  useEffect(() => {
    if (!sessionId || pendingCreate) return;
    // If we have active streaming messages, don't clobber them with DB fetch
    setConv(prev => {
      if (prev.messages.some(m => m.streaming)) return prev;
      return prev;
    });
    setHasCreatedSession(true);
    chatApi.getSession(sessionId).then(detail => {
      const sessionMode = detail.session.mode || 'react';
      // Lock mode to the session's mode when recovering history
      setMode(sessionMode);
      const msgs = (detail.messages || []).map((m: BackendMsg) => {
        let result: Record<string, unknown> | undefined;
        if (m.result_summary) {
          try { result = JSON.parse(m.result_summary); } catch { /* ignore */ }
        }
        return {
          id: m.id, role: m.role as Message['role'], content: m.content, mode: m.mode,
          timestamp: new Date(m.created_at).getTime(), streaming: false,
          result,
        } as Message;
      });
      // Only update if we don't have local streaming messages
      setConv(prev => {
        if (prev.messages.some(m => m.streaming)) return prev;
        return { id: sessionId, title: detail.session.title, mode: sessionMode, messages: msgs, createdAt: Date.now(), updatedAt: Date.now() };
      });
    }).catch(() => {});
  }, [sessionId]);

  // Handle draftInput from scenario/template
  useEffect(() => {
    if (draftInput && draftInput.trim()) {
      setInput(draftInput);
      if (draftMode) setMode(draftMode);
      onDraftConsumed?.();
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [draftInput]);

  // Reset hasCreatedSession when new conversation
  useEffect(() => {
    if (!sessionId && pendingCreate) setHasCreatedSession(false);
  }, [sessionId, pendingCreate]);

  useEffect(() => { msgEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [conv.messages]);

  const doSubmit = useCallback(async (text: string, submitMode: string) => {
    if (!text.trim() || loading) return;
    setInput('');

    // CRITICAL: Show user message + assistant skeleton IMMEDIATELY before any async work.
    // Use flushSync to force React to render NOW, not later.
    const userMsg: Message = { id: 'um_' + Date.now(), role: 'user', content: text.trim(), mode: submitMode, timestamp: Date.now() };
    const skelId = 'am_' + Date.now() + '_loading';
    flushSync(() => {
      setConv(prev => ({
        ...prev,
        messages: [...prev.messages, userMsg, { id: skelId, role: 'assistant', mode: submitMode, content: '正在创建会话并分析...', timestamp: Date.now(), streaming: true } as Message],
      }));
      setStreamingMsgId(skelId);
      setLoading(true);
    });
    // Yield to browser: let React commit and paint
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));

    // Phase 8: Try SSE stream first, fallback to REST
    try {
      await streamChat(
        { sessionId: sessionId || undefined, content: text.trim(), mode: submitMode },
        {
          onSessionCreated: (sid) => {
            if (!sessionId) { onSessionCreated?.(sid); setHasCreatedSession(true); setConv(prev => ({ ...prev, id: sid })); }
          },
          onStep: (_stage, stepText) => { updateStreaming(skelId, stepText); },
          onEvidence: () => { /* evidence displayed in collapsing detail */ },
          onDelta: (deltaText) => {
            setConv(prev => {
              const msgs = prev.messages.map(m =>
                m.id === skelId ? { ...m, content: (m.content + deltaText).replace(/^正在.*\.\.\./, '') } as Message : m
              );
              return { ...prev, messages: msgs };
            });
          },
          onDone: (data) => {
            setConv(prev => ({
              ...prev,
              messages: prev.messages.map(m => {
                if (m.id !== skelId) return m;
                // Use content from done event if no deltas arrived (e.g. abstain path)
                const doneContent = (data.content || data.answer || '') as string;
                const finalContent = m.content.replace(/^正在.*\.\.\./, '') || doneContent;
                return {
                  ...m,
                  content: finalContent || doneContent || m.content,
                  streaming: false,
                  result: data as unknown as R,
                } as Message;
              }),
            }));
            onConversationUpdate?.();
          },
          onError: () => { throw new Error('SSE stream failed'); },
        }
      );
    } catch (_sseError) {
      // Fallback to REST API
      try {
        let sid = sessionId;
        if (!sid && !hasCreatedSession && pendingCreate) {
          updateStreaming(skelId, '正在创建会话...');
          const s = await chatApi.createSession(submitMode);
          sid = s.sessionId;
          onSessionCreated?.(sid); setHasCreatedSession(true);
          setConv(prev => ({ ...prev, id: s.sessionId }));
        }
        if (!sid) throw new Error('无法获取会话ID');
        // Phase20 R2：REST 降级路径只允许中性状态，不伪造「正在检索/Agent 正在分析」等步骤
        updateStreaming(skelId, '正在处理请求…');
        const resp = await chatApi.sendMessage(sid, text.trim(), submitMode);
        const answer = (resp.assistantMessage.content as string) || '';
        const note = resp.abstained ? '\n\n⚠ 证据不足' : '';
        await streamText(skelId, answer + note, (c) => updateStreaming(skelId, c));
        setConv(prev => ({
          ...prev,
          messages: prev.messages.map(m => m.id === skelId ? { ...m, content: answer + note, streaming: false, result: resp as unknown as R } as Message : m),
        }));
        onConversationUpdate?.();
      } catch (e) {
        const err = e instanceof Error ? e.message : '请求失败';
        setConv(prev => ({ ...prev, messages: prev.messages.map(m => m.id === skelId ? { ...m, content: '❌ ' + err, streaming: false } as Message : m) }));
      }
    } finally {
      setLoading(false); setStreamingMsgId(null);
    }
  }, [conv, loading, sessionId, pendingCreate, hasCreatedSession, onSessionCreated]);

  function updateStreaming(id: string, content: string) {
    // Use flushSync to force React to render immediately (needed for streaming effect)
    flushSync(() => {
      setConv(prev => ({ ...prev, messages: prev.messages.map(m => m.id === id ? { ...m, content } as Message : m) }));
    });
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 16, minHeight: 200 }}>
        {conv.messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF', fontSize: 14 }}>
            <RobotOutlined style={{ fontSize: 32, color: '#D1D5DB', marginBottom: 12 }} />
            <div>{view === 'multi' ? '输入事件信息启动多Agent协同研判' : view === 'analyze' ? '输入事件信息进行风险研判' : '输入问题或选择场景模板开始'}</div>
            {view === 'multi' && <div style={{ fontSize: 12, marginTop: 8 }}>建议提供: roadName / eventType / avgSpeed / queueLength / duration / weather</div>}
            {view === 'similar' && <div style={{ fontSize: 12, marginTop: 8, color: '#0F766E' }}>混合相似度=规则(0.6)+向量(0.4)，点击左侧已有事件快速检索</div>}
          </div>
        )}
        {conv.messages.map(msg => (
          <div key={msg.id} style={{ display: 'flex', gap: 10, marginBottom: 16, flexDirection: msg.role === 'user' ? 'row-reverse' : 'row' }}>
            <div style={{ flexShrink: 0 }}>
              {msg.role === 'user'
                ? <div style={{ width: 36, height: 36, borderRadius: 18, background: '#E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><UserOutlined style={{ color: '#6B7280' }} /></div>
                : msg.streaming ? <ThinkingAvatar />
                  : <div style={{ width: 36, height: 36, borderRadius: 18, background: '#F0FDFA', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><RobotOutlined style={{ color: '#0F766E' }} /></div>}
            </div>
            <div style={{ flex: 1, minWidth: 0, maxWidth: msg.role === 'user' ? '70%' : '100%' }}>
              <div style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 2, textAlign: msg.role === 'user' ? 'right' : 'left' }}>
                {msg.role === 'user' ? '你' : 'TrafficMind'} · {new Date(msg.timestamp).toLocaleTimeString()}
                <Tag style={{ marginLeft: 6, fontSize: 10 }}>{msg.mode}</Tag>
              </div>
              <div style={{
                background: msg.role === 'user' ? '#0F766E' : '#FFF', color: msg.role === 'user' ? '#FFF' : '#111827',
                borderRadius: msg.role === 'user' ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
                padding: '12px 16px', fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap',
                border: msg.role === 'assistant' ? '1px solid #E5E7EB' : 'none',
              }}>
                {msg.streaming ? (msg.content || '▊') : msg.content.startsWith('❌')
                  ? <div style={{ color: '#EF4444' }}><WarningOutlined style={{ marginRight: 6 }} />{msg.content.replace('❌ ', '')}<div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>请确认后端已启动</div></div>
                  : msg.content}
              </div>
              {msg.role === 'assistant' && !msg.streaming && msg.result && (
                <Collapse size="small" ghost items={[{ key: 'detail', label: <span style={{ fontSize: 11, color: '#9CA3AF' }}>查看详情</span>,
                  children: <ResultTags result={msg.result as R} /> }]} />
              )}
              {msg.role === 'assistant' && !msg.streaming && msg.result && (
                (() => {
                  const res = msg.result as R;
                  const traceId = (res.traceId || res.trace_id) as string | undefined;
                  const evidenceRaw = (res.evidence) as unknown[];
                  const evidence: RagEvidenceItem[] = (evidenceRaw || []).map((e: unknown) => {
                    const item = e as Record<string, unknown>;
                    const getStr = (k1: string, k2: string) => {
                      const v = item[k1] ?? item[k2];
                      return typeof v === 'string' ? v : undefined;
                    };
                    const getNum = (k1: string, k2: string) => {
                      const v = item[k1] ?? item[k2];
                      return typeof v === 'number' ? v : undefined;
                    };
                    return {
                      evidenceId: String(item.evidenceId ?? item.evidence_id ?? ''),
                      chunkId: String(item.chunkId ?? item.chunk_id ?? ''),
                      documentId: String(item.documentId ?? item.document_id ?? ''),
                      parentChunkId: getStr('parentChunkId', 'parent_chunk_id'),
                      title: String(item.title ?? ''),
                      sectionPath: String(item.sectionPath ?? item.section_path ?? ''),
                      docType: (String(item.docType ?? item.doc_type ?? 'other')) as RagEvidenceItem['docType'],
                      content: String(item.content ?? ''),
                      contextualContent: String(item.contextualContent ?? item.contextual_content ?? ''),
                      authorityLevel: (String(item.authorityLevel ?? item.authority_level ?? 'operational')) as RagEvidenceItem['authorityLevel'],
                      effectiveFrom: getStr('effectiveFrom', 'effective_from'),
                      effectiveTo: getStr('effectiveTo', 'effective_to'),
                      retrievalChannels: (Array.isArray(item.retrievalChannels) ? item.retrievalChannels : Array.isArray(item.retrieval_channels) ? item.retrieval_channels : []) as string[],
                      rrfScore: getNum('rrfScore', 'rrf_score'),
                      rerankScore: getNum('rerankScore', 'rerank_score'),
                      sourceUri: getStr('sourceUri', 'source_uri'),
                    };
                  });
                  if (traceId) {
                    return <RagTracePanel traceId={traceId} evidence={evidence} />;
                  }
                  return null;
                })()
              )}
            </div>
          </div>
        ))}
        {loading && !streamingMsgId && <div style={{ textAlign: 'center', padding: 8 }}><Spin size="small" /> 分析中...</div>}
        <div ref={msgEnd} />
      </div>

      {/* Phase20 R2：相关 Workflow Runs（session-level 真实关系，0..N 全部展示） */}
      {sessionId && onOpenWorkflowRun && (
        <RelatedWorkflowRuns sessionId={sessionId} onOpenRun={onOpenWorkflowRun} />
      )}

      {/* Input */}
      <div style={{ background: '#FFF', borderRadius: 20, border: '1px solid #E5E7EB', padding: '8px 12px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)', marginTop: 8 }}>
        <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {showFullModes ? (
            ['react', 'routed', 'rag', 'hybrid', 'report', 'collaboration'].map(k => (
              <button key={k} onClick={() => setMode(k)}
                style={{ border: 'none', borderRadius: 20, padding: '4px 12px', fontSize: 12, cursor: 'pointer', background: mode === k ? '#F0FDFA' : '#F9FAFB', color: mode === k ? '#0F766E' : '#6B7280', fontWeight: mode === k ? 600 : 400 }}>
                {{ react: '🤖 智能诊断', routed: '🔍 事件研判', rag: '📖 知识问答', hybrid: '📊 相似案例', report: '📋 报告生成', collaboration: '🤝 协同分析' }[k]}
              </button>
            ))
          ) : (
            <span style={{ fontSize: 12, color: '#9CA3AF' }}>
              当前能力：<strong style={{ color: '#0F766E' }}>{{ react: '智能诊断', routed: '事件研判', rag: '知识问答', hybrid: '相似案例', report: '报告生成', collaboration: '协同分析' }[mode]}</strong>
              <select value={mode} onChange={e => setMode(e.target.value)}
                style={{ marginLeft: 6, border: '1px solid #E5E7EB', borderRadius: 8, padding: '2px 6px', fontSize: 11, color: '#6B7280', background: '#FFF' }}>
                <option value="react">智能诊断</option><option value="routed">事件研判</option><option value="rag">知识问答</option><option value="hybrid">相似案例</option><option value="report">报告生成</option><option value="collaboration">协同分析</option>
              </select>
            </span>
          )}
          {onNewConversation && (
            <button onClick={onNewConversation} style={{ marginLeft: 'auto', border: '1px solid #E5E7EB', borderRadius: 10, padding: '4px 10px', background: '#FFF', cursor: 'pointer', fontSize: 11, color: '#6B7280', whiteSpace: 'nowrap' }}>
              <PlusOutlined /> 新对话
            </button>
          )}
        </div>
        {!showFullModes && (
          <div style={{ fontSize: 10, color: '#D1D5DB', marginBottom: 4 }}>左侧用于切换业务工作区，输入框能力用于决定本次问题调用哪类分析链路。</div>
        )}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSubmit(input, mode); } }}
            placeholder={view === 'multi' ? '输入事件信息...' : '输入问题...'} rows={2}
            style={{ flex: 1, border: 'none', outline: 'none', resize: 'none', fontSize: 14, color: '#111827', background: 'transparent', fontFamily: 'inherit', lineHeight: 1.5 }} />
          <button onClick={() => doSubmit(input, mode)} disabled={loading || !input.trim()}
            style={{ width: 40, height: 40, borderRadius: 20, border: 'none', background: loading || !input.trim() ? '#E5E7EB' : '#0F766E', color: '#FFF', cursor: loading || !input.trim() ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, flexShrink: 0 }}>
            <SendOutlined />
          </button>
        </div>
      </div>
    </div>
  );
}

function ResultTags({ result }: { result: R }) {
  const e = result.evidence as unknown[] | undefined;
  const c = result.conflicts as unknown[] | undefined;
  const a = result.selectedAgents as string[] | undefined;
  const abstained = Boolean(result.abstained);
  return (
    <div style={{ fontSize: 11, color: '#6B7280', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {abstained && <Tag color="orange">证据不足</Tag>}
      {result.confidence != null && <Tag>置信度 {String(result.confidence)}</Tag>}
      {e && e.length > 0 && <Tag color="blue">{e.length}条证据</Tag>}
      {a && a.length > 0 && <Tag color="cyan">{a.length}Agents</Tag>}
      {c && c.length > 0 && <Tag color="red">{c.length}冲突</Tag>}
    </div>
  );
}
