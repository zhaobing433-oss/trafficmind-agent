/**
 * API 调用封装
 * 开发环境下通过 Vite proxy 转发 /api → localhost:8000
 */

import type {
  AnalyzeEventRequest,
  AnalyzeResult,
  EventRecord,
  StatsResponse,
} from '../types';

const BASE = '/api';

/** 通用 GET 请求 */
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/** 通用 POST 请求 */
async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/** 获取仪表盘统计数据 */
export function getStats(): Promise<StatsResponse> {
  return get<StatsResponse>('/stats');
}

/** 获取历史事件列表 */
export function getHistory(limit = 50): Promise<{ total: number; records: EventRecord[] }> {
  return get(`/history?limit=${limit}`);
}

/** 获取单条事件详情 */
export function getEventById(eventId: string): Promise<AnalyzeResult> {
  return get(`/event/${eventId}`);
}

/** 分析交通事件 */
export function analyzeEvent(data: AnalyzeEventRequest): Promise<AnalyzeResult> {
  return post<AnalyzeResult>('/analyze_event', data);
}

/** 更新事件状态 */
export function updateEventStatus(
  eventId: string,
  status: string
): Promise<{ eventId: string; status: string; message: string }> {
  return post(`/event/${eventId}/status`, { status });
}
