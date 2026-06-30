/**
 * API 调用封装 — 第二阶段扩展
 * 开发环境下通过 Vite proxy 转发 /api → localhost:8000
 */

import type {
  AnalyzeEventRequest,
  AnalyzeResult,
  EventRecord,
  StatsResponse,
  SimilarCasesResponse,
  DailyReportResponse,
  WeeklyReportResponse,
  UnclosedAlertsResponse,
  HighRiskRoadsResponse,
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

// ========== 第一阶段接口 ==========

export function getStats(): Promise<StatsResponse> {
  return get<StatsResponse>('/stats');
}

export function getHistory(limit = 50): Promise<{ total: number; records: EventRecord[] }> {
  return get(`/history?limit=${limit}`);
}

export function getEventById(eventId: string): Promise<AnalyzeResult> {
  return get(`/event/${eventId}`);
}

export function analyzeEvent(data: AnalyzeEventRequest): Promise<AnalyzeResult> {
  return post<AnalyzeResult>('/analyze_event', data);
}

export function updateEventStatus(
  eventId: string,
  status: string
): Promise<{ eventId: string; status: string; message: string }> {
  return post(`/event/${eventId}/status`, { status });
}

// ========== 第二阶段新增接口 ==========

/** 历史相似案例检索 */
export function getSimilarCases(
  eventId: string,
  limit = 5,
  minScore = 0.4
): Promise<SimilarCasesResponse> {
  return get<SimilarCasesResponse>(
    `/similar_cases/${eventId}?limit=${limit}&min_score=${minScore}`
  );
}

/** 交通事件日报 */
export function getDailyReport(date?: string): Promise<DailyReportResponse> {
  const params = date ? `?date=${date}` : '';
  return get<DailyReportResponse>(`/reports/daily${params}`);
}

/** 交通事件周报 */
export function getWeeklyReport(
  startDate?: string,
  endDate?: string
): Promise<WeeklyReportResponse> {
  const params: string[] = [];
  if (startDate) params.push(`start_date=${startDate}`);
  if (endDate) params.push(`end_date=${endDate}`);
  const qs = params.length ? `?${params.join('&')}` : '';
  return get<WeeklyReportResponse>(`/reports/weekly${qs}`);
}

/** 未闭环事件提醒 */
export function getUnclosedAlerts(
  hours = 24,
  minRisk = '中风险'
): Promise<UnclosedAlertsResponse> {
  return get<UnclosedAlertsResponse>(
    `/alerts/unclosed?hours=${hours}&min_risk=${encodeURIComponent(minRisk)}`
  );
}

/** 高风险路口 TopN */
export function getHighRiskRoads(
  limit = 10,
  days = 7,
  minRisk = '高风险'
): Promise<HighRiskRoadsResponse> {
  return get<HighRiskRoadsResponse>(
    `/stats/high_risk_roads?limit=${limit}&days=${days}&min_risk=${encodeURIComponent(minRisk)}`
  );
}
