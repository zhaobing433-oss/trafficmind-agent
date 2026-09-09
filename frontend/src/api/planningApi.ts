/** Phase17 Planning API 客户端 */

import type {
  PlanListResponse, PlanDetailResponse, VersionDiff, TrajectoryResponse, ObservationItem,
} from '../types/planning';

const API = '/api';

export async function listPlans(params: { page?: number; pageSize?: number; goalType?: string; status?: string; search?: string; eventId?: string } = {}): Promise<PlanListResponse> {
  const q = new URLSearchParams();
  if (params.page) q.set('page', String(params.page));
  if (params.pageSize) q.set('pageSize', String(params.pageSize));
  if (params.goalType) q.set('goalType', params.goalType);
  if (params.status) q.set('status', params.status);
  if (params.search) q.set('search', params.search);
  if (params.eventId) q.set('eventId', params.eventId);
  const resp = await fetch(`${API}/planning/plans?${q.toString()}`);
  if (!resp.ok) throw new Error(`list plans failed: ${resp.status}`);
  return resp.json();
}

export async function createPlanFromAgent(body: {
  eventId: string;
  sessionId?: string;
  collaborationRunId: string;
  plannerMode?: 'deterministic';
}): Promise<Record<string, unknown>> {
  const resp = await fetch(`${API}/planning/plans/from-agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plannerMode: 'deterministic', ...body }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(formatApiError(err) || `create plan from agent failed: ${resp.status}`);
  }
  return resp.json();
}

export async function runPlan(
  planId: string,
  body: { event?: Record<string, unknown>; sessionId?: string; eventThreadId?: string; triggeredBy?: string },
  callbacks: {
    onEvent?: (eventType: string, data: Record<string, unknown>) => void;
    onError?: (error: string) => void;
    onDone?: (status: string) => void;
    signal?: AbortSignal;
  } = {},
): Promise<void> {
  const resp = await fetch(`${API}/planning/plans/${encodeURIComponent(planId)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: callbacks.signal,
  });
  await consumePlanSSE(resp, callbacks);
}

export async function getPlan(planId: string): Promise<PlanDetailResponse> {
  const resp = await fetch(`${API}/planning/plans/${encodeURIComponent(planId)}`);
  if (!resp.ok) throw new Error(`get plan failed: ${resp.status}`);
  return resp.json();
}

export async function getPlanDiff(planId: string, fromVersion: number, toVersion: number): Promise<VersionDiff> {
  const resp = await fetch(`${API}/planning/plans/${encodeURIComponent(planId)}/diff?fromVersion=${fromVersion}&toVersion=${toVersion}`);
  if (!resp.ok) throw new Error(`diff failed: ${resp.status}`);
  return resp.json();
}

export async function getTrajectory(runId: string): Promise<TrajectoryResponse> {
  const resp = await fetch(`${API}/planning/runs/${encodeURIComponent(runId)}/trajectory`);
  if (!resp.ok) throw new Error(`trajectory failed: ${resp.status}`);
  return resp.json();
}

export async function listObservations(runId: string): Promise<{ runId: string; observations: ObservationItem[] }> {
  const resp = await fetch(`${API}/planning/runs/${encodeURIComponent(runId)}/observations`);
  if (!resp.ok) throw new Error(`observations failed: ${resp.status}`);
  return resp.json();
}

function formatApiError(value: unknown): string {
  const detail = value && typeof value === 'object' ? (value as { detail?: unknown }).detail : null;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return '';
}

async function consumePlanSSE(
  response: Response,
  callbacks: {
    onEvent?: (eventType: string, data: Record<string, unknown>) => void;
    onError?: (error: string) => void;
    onDone?: (status: string) => void;
  },
): Promise<void> {
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    callbacks.onError?.(formatApiError(err) || `HTTP ${response.status}`);
    return;
  }
  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError?.('Response body is not readable');
    return;
  }
  const decoder = new TextDecoder();
  let buffer = '';
  let doneEvent = false;
  while (!doneEvent) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    let eventType = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) eventType = line.slice(7).trim();
      else if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          if (eventType === 'done') {
            doneEvent = true;
            callbacks.onDone?.(String(data.status || 'completed'));
          } else if (eventType === 'error') {
            callbacks.onError?.(String(data.message || '执行失败'));
          } else {
            callbacks.onEvent?.(eventType || 'message', data);
          }
        } catch {
          // Ignore malformed SSE fragments.
        }
      }
    }
  }
  if (!doneEvent) callbacks.onDone?.('interrupted');
}
