/**
 * SSE 流式 API — 消费后端 Server-Sent Events
 */
const API = '/api';

interface StreamCallbacks {
  onSessionCreated?: (sessionId: string) => void;
  onMessageSaved?: (userMessageId: string) => void;
  onStep?: (stage: string, text: string) => void;
  onEvidence?: (items: Record<string, unknown>[]) => void;
  onDelta?: (text: string) => void;
  onDone?: (data: Record<string, unknown>) => void;
  onError?: (message: string) => void;
  // Agent stream callbacks
  onAgentStart?: (agentName: string, text: string) => void;
  onAgentResult?: (result: Record<string, unknown>) => void;
  onFusionDelta?: (text: string) => void;
  onFusionDone?: (summary: string) => void;
  onConflictDone?: (conflicts: unknown[], count: number) => void;
}

export async function streamChat(
  body: { sessionId?: string; content: string; mode?: string },
  callbacks: StreamCallbacks
): Promise<void> {
  await consumeSSE(`${API}/chat/stream`, body, callbacks);
}

export async function streamRoutedAnalyze(
  body: Record<string, unknown>,
  callbacks: StreamCallbacks
): Promise<void> {
  // Force sessionId: convert undefined → null so JSON.stringify includes it
  const reqBody = {
    ...body,
    sessionId: body.sessionId ?? null,
    content: body.content ?? '',
    mode: body.mode ?? 'collaboration',
    contextPolicy: body.contextPolicy ?? 'fresh_event',
  };
  await consumeSSE(`${API}/agent/routed_analyze/stream`, reqBody, callbacks);
}

async function consumeSSE(
  url: string,
  body: Record<string, unknown>,
  callbacks: StreamCallbacks
): Promise<void> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
    callbacks.onError?.(err.detail || '请求失败');
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) { callbacks.onError?.('Stream not available'); return; }

  const decoder = new TextDecoder();
  let buffer = '';
  let streamDone = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let currentEvent = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const dataStr = line.slice(6);
          try {
            const data = JSON.parse(dataStr);
            dispatchEvent(currentEvent, data, callbacks);
            // Stop reading immediately when done/error received
            if (currentEvent === 'done' || currentEvent === 'error') {
              streamDone = true;
            }
          } catch { /* skip malformed JSON */ }
        }
      }
      if (streamDone) break;
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

function dispatchEvent(event: string, data: Record<string, unknown>, cbs: StreamCallbacks) {
  switch (event) {
    case 'session_created': cbs.onSessionCreated?.(data.sessionId as string); break;
    case 'message_saved': cbs.onMessageSaved?.(data.userMessageId as string); break;
    case 'step': cbs.onStep?.(data.stage as string, data.text as string); break;
    case 'evidence': cbs.onEvidence?.(data.items as Record<string, unknown>[]); break;
    case 'delta': cbs.onDelta?.(data.text as string); break;
    case 'done': cbs.onDone?.(data); break;
    case 'error': cbs.onError?.(data.message as string); break;
    // RAG V2 events — consumed by RagTracePanel via persisted result
    case 'rag_route_done': break;
    case 'rag_query_rewritten': break;
    case 'rag_candidates_retrieved': break;
    case 'rag_rerank_done': break;
    case 'rag_evidence_selected': break;
    case 'rag_abstained': break;
    case 'rag_trace_ready': break;
    case 'agent_start': cbs.onAgentStart?.(data.agentName as string, data.text as string); break;
    case 'agent_result': cbs.onAgentResult?.(data); break;
    case 'fusion_delta': cbs.onFusionDelta?.(data.text as string); break;
    case 'fusion_done': cbs.onFusionDone?.(data.fusionSummary as string); break;
    case 'conflict_check_done': cbs.onConflictDone?.(data.conflicts as unknown[], data.conflictCount as number); break;
    case 'event_parse_start': cbs.onStep?.('parse', data.text as string); break;
    case 'event_parse_done': cbs.onStep?.('parse_done', `事件类型: ${data.eventType || ''} ${data.roadName || ''}`); break;
    case 'agent_route_done': cbs.onStep?.('route', `已选择 Agent: ${(data.selectedAgents as string[])?.join(', ')}`); break;
  }
}
