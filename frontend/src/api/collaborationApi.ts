/** 协作运行 API — 蛇形/驼峰归一化 */
const API = '/api';

/** 递归归一化任务节点 */
function normalizeTask(raw: Record<string,unknown>): Record<string,unknown> {
  return {
    taskId: raw.taskId ?? raw.task_id ?? '',
    agentName: raw.agentName ?? raw.agent_name ?? '',
    taskType: raw.taskType ?? raw.task_type ?? 'analyze',
    dependsOn: raw.dependsOn ?? raw.depends_on ?? [],
    status: raw.status ?? 'pending',
    priority: raw.priority ?? 5,
    attempt: raw.attempt ?? 0,
    maxRetries: raw.maxRetries ?? raw.max_retries ?? 1,
    timeoutSeconds: raw.timeoutSeconds ?? raw.timeout_seconds ?? 30,
    startedAt: raw.startedAt ?? raw.started_at ?? '',
    completedAt: raw.completedAt ?? raw.completed_at ?? '',
    error: raw.error ?? raw.errorMessage ?? raw.error_message ?? '',
  };
}

/** 将 snake_case SSE 数据归一化为 camelCase */
function normalizeEvent(raw: Record<string, unknown>): Record<string, unknown> {
  const map: Record<string, string> = {
    run_id: 'runId', trace_id: 'traceId', session_id: 'sessionId', task_id: 'taskId',
    agent_name: 'agentName', task_type: 'taskType', depends_on: 'dependsOn',
    max_retries: 'maxRetries', timeout_seconds: 'timeoutSeconds',
    input_snapshot: 'inputSnapshot', output_snapshot: 'outputSnapshot',
    error_code: 'errorCode', error_message: 'errorMessage',
    started_at: 'startedAt', completed_at: 'completedAt',
    selected_agents: 'selectedAgents', skipped_agents: 'skippedAgents',
    routing_reasons: 'routingReasons', agent_results: 'agentResults',
    failed_agents: 'failedAgents', budget_usage: 'budgetUsage',
    final_decision: 'finalDecision', fusion_summary: 'fusionSummary',
    requires_human_review: 'requiresHumanReview', fallback_reason: 'fallbackReason',
    protocol_version: 'protocolVersion', execution_engine: 'executionEngine',
    sequence_number: 'sequenceNumber', event_type: 'eventType',
    evidence_refs: 'evidenceRefs', conflict_count: 'conflictCount',
    max_agents: 'maxAgents', max_agent_calls: 'maxAgentCalls', max_total_seconds: 'maxTotalSeconds',
    used_agent_calls: 'usedAgentCalls', used_retries: 'usedRetries',
  };
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    const mapped = map[k] || k;
    if (k === 'tasks' || k === 'taskGraph') {
      // Special handling: normalize each task node
      out[mapped] = Array.isArray(v) ? v.map(item => normalizeTask(item as Record<string,unknown>)) : v;
    } else if (typeof v === 'object' && v !== null && !Array.isArray(v)) {
      out[mapped] = normalizeEvent(v as Record<string, unknown>);
    } else if (Array.isArray(v)) {
      out[mapped] = v.map(item => typeof item === 'object' && item !== null ? normalizeEvent(item as Record<string, unknown>) : item);
    } else {
      out[mapped] = v;
    }
  }
  return out;
}

export interface RunListItem { run_id: string; session_id: string; status: string; selected_agents: string; started_at: string; updated_at: string; }

async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error('请求失败');
  return r.json();
}

export const collabApi = {
  listSessionRuns: (sessionId: string) =>
    apiGet<{ runs: RunListItem[] }>(`/collaboration/sessions/${sessionId}/runs`).then(d => d.runs),

  getRun: (runId: string) =>
    apiGet<{ run: Record<string,unknown>; tasks: Record<string,unknown>[]; messages: Record<string,unknown>[]; conflicts: Record<string,unknown>[]; events: Record<string,unknown>[] }>(`/collaboration/runs/${runId}`),

  streamCollaboration: (
    body: Record<string, unknown>,
    callbacks: {
      onEvent?: (event: Record<string, unknown>) => void;
      onError?: (err: string) => void;
      onDone?: (data: Record<string, unknown>) => void;
      signal?: AbortSignal;
    }
  ): Promise<void> => {
    const { onEvent, onError, onDone, signal } = callbacks;
    return fetch(`${API}/agent/routed_analyze/stream`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal,
    }).then(async response => {
      if (!response.ok) { onError?.(`HTTP ${response.status}`); return; }
      const reader = response.body?.getReader();
      if (!reader) { onError?.('No stream'); return; }
      const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n'); buffer = lines.pop() || '';
        let currentEvent = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) { currentEvent = line.slice(7).trim(); }
          else if (line.startsWith('data: ')) {
            try { const raw = JSON.parse(line.slice(6)); const data = normalizeEvent(raw); data.eventType = data.eventType || currentEvent; onEvent?.(data); if (currentEvent === 'done') onDone?.(data); }
            catch { /* skip */ }
          }
        }
      }
    }).catch(e => { if (e.name !== 'AbortError') onError?.(e.message); });
  },
};
