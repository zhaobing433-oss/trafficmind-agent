import { eventTitle } from './display';
import type { RunListItem } from '../api/collaborationApi';
import type { RecentJudgments, SessionJudgments } from '../types/judgment';

export function record(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') { try { return record(JSON.parse(value)); } catch { return {}; } }
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
export function text(value: unknown): string { return typeof value === 'string' ? value.trim() : ''; }
export function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(x => x && typeof x === 'object' && !Array.isArray(x)) : [];
}
export function strings(value: unknown): string[] { return Array.isArray(value) ? value.map(text).filter(Boolean) : []; }
export function judgmentTime(run: RunListItem): string { return run.completed_at || run.started_at || run.updated_at || ''; }
const time = (value: string) => Date.parse(value) || 0;
export function latestJudgment(runs: RunListItem[]): RunListItem | undefined {
  return [...runs].sort((a, b) => time(judgmentTime(b)) - time(judgmentTime(a)) || a.run_id.localeCompare(b.run_id))[0];
}
export function judgmentTitle(value: unknown): string {
  const event = record(value);
  return eventTitle({ roadName: text(event.roadName), eventTypeCn: text(event.eventTypeCn), eventType: text(event.eventType) });
}

export function groupRecentJudgments(sessions: SessionJudgments[]): RecentJudgments {
  const byEvent = new Map<string, RunListItem[]>();
  const seen = new Set<string>();
  const legacy: RecentJudgments['legacy'] = [], failedSessions: RecentJudgments['failedSessions'] = [];
  for (const { session, runs, error } of sessions) {
    if (error) { failedSessions.push(session); continue; }
    if (runs.some(run => !run.run_id || run.session_id !== session.id)) { failedSessions.push(session); continue; }
    const unbound: RunListItem[] = [];
    for (const run of runs) {
      const eventId = text(record(run.normalized_event).eventId);
      if (!eventId) { unbound.push(run); continue; }
      if (seen.has(run.run_id)) continue;
      seen.add(run.run_id);
      byEvent.set(eventId, [...(byEvent.get(eventId) || []), run]);
    }
    if (unbound.length || runs.length === 0) legacy.push({ ...session, unboundRunId: latestJudgment(unbound)?.run_id });
  }
  const events = [...byEvent].map(([eventId, runs]) => {
    const latest = latestJudgment(runs)!;
    return { eventId, businessTitle: judgmentTitle(latest.normalized_event), lastJudgedAt: judgmentTime(latest),
      judgmentLoaded: runs.length, latestSessionId: latest.session_id, latestRunId: latest.run_id, latestStatus: latest.status };
  }).sort((a, b) => time(b.lastJudgedAt) - time(a.lastJudgedAt) || a.eventId.localeCompare(b.eventId));
  return { events, legacy, failedSessions, sessionsLoaded: sessions.length, runsLoaded: seen.size };
}

export function selectJudgmentRun(runs: RunListItem[], requestedRunId?: string | null): string {
  return requestedRunId || [...runs].sort((a, b) => time(b.started_at) - time(a.started_at) || b.run_id.localeCompare(a.run_id))[0]?.run_id || '';
}

export function provenanceLabel(value: unknown): string {
  const source = record(value);
  const type = text(record(source.provenance).sourceType) || text(source.sourceType) || text(source.verificationStatus);
  return ({ real_public_verified: '公开区域资料', real_public_source_grounded: '公开法规/规则',
    synthetic_validation: '合成历史样本 · 用于验证', synthetic_validation_holdout: '合成历史样本 · 用于验证',
    synthetic_event_system_closure: '系统闭环验证案例', synthetic_case_seed: '系统闭环验证案例' } as Record<string, string>)[type] || '来源未核验';
}

export function caseOutcome(status: unknown): string {
  return ({ completed: '已完成流程', rejected: '已驳回', failed: '执行失败', cancelled: '已取消' } as Record<string, string>)[text(status)] || '流程结果未记录';
}
