import type { RunListItem, EventRunListResponse } from '../../api/collaborationApi';
import type { PlanListItem, PlanListResponse, PlanDetailResponse } from '../../types/planning';
import type { RunListResponse, RunSummary } from '../../types/workflow';

export type QueryStatus = 'IDLE' | 'LOADING' | 'SUCCESS_EMPTY' | 'SUCCESS_WITH_DATA' | 'ERROR';
export interface Relation<T> {
  status: QueryStatus;
  items: T[];
  total: number | null;
  error?: string;
}
export type EventPlan = PlanListItem & { detail?: PlanDetailResponse['plan'] };
export interface EventRelations {
  eventId: string | null;
  revision: number;
  collaboration: Relation<RunListItem>;
  plan: Relation<EventPlan>;
  workflow: Relation<RunSummary>;
}
export interface RelationSources {
  collaboration: (eventId: string) => Promise<EventRunListResponse>;
  plan: (eventId: string) => Promise<PlanListResponse>;
  planDetail: (planId: string) => Promise<PlanDetailResponse>;
  workflow: (eventId: string) => Promise<RunListResponse>;
}

const empty = <T>(status: QueryStatus): Relation<T> => ({ status, items: [], total: null });
export function pendingRelations(eventId: string | null, revision: number): EventRelations {
  const status = eventId ? 'LOADING' : 'IDLE';
  return { eventId, revision, collaboration: empty(status), plan: empty(status), workflow: empty(status) };
}

// Selection/retry changes must hide the old snapshot before useEffect starts its request.
export function relationsForSelection(state: EventRelations, eventId: string | null, revision: number): EventRelations {
  return state.eventId === eventId && state.revision === revision ? state : pendingRelations(eventId, revision);
}

export function objectValue(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try { return objectValue(JSON.parse(value)); } catch { return {}; }
  }
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function page<T>(items: T[], total: number, id: (item: T) => string): Relation<T> {
  if (!Array.isArray(items) || !Number.isInteger(total) || total < items.length ||
      (total > 0 && items.length === 0) || items.some(item => !id(item)) ||
      new Set(items.map(id)).size !== items.length) throw new Error('关联接口返回不完整，请重试');
  return { status: total === 0 ? 'SUCCESS_EMPTY' : 'SUCCESS_WITH_DATA', items, total };
}

export function newest<T>(items: T[], time: (item: T) => string | null | undefined): T | null {
  const score = (item: T) => Date.parse(time(item) || '') || 0;
  return [...items].sort((a, b) => score(b) - score(a))[0] || null;
}
export const currentCollaboration = (r: EventRelations) => newest(r.collaboration.items, x => x.started_at || x.updated_at);
export const currentPlan = (r: EventRelations) => newest(r.plan.items, x => x.updatedAt || x.createdAt);
export const currentWorkflow = (r: EventRelations) => newest(r.workflow.items, x => x.startedAt || x.updatedAt);

export function verifiedJudgmentSessionId(relations: EventRelations): string | null {
  if (!relations.eventId || relations.collaboration.status !== 'SUCCESS_WITH_DATA') return null;
  const matching = relations.collaboration.items.filter(run =>
    objectValue(run.normalized_event).eventId === relations.eventId && Boolean(run.session_id?.trim()),
  );
  return newest(matching, run => run.started_at || run.updated_at)?.session_id.trim() || null;
}

export function loadEventRelations(eventId: string, revision: number, sources: RelationSources, publish: (state: EventRelations) => void): () => void {
  let cancelled = false;
  let state = pendingRelations(eventId, revision);
  publish(state);
  const load = <K extends 'collaboration' | 'plan' | 'workflow'>(key: K, request: () => Promise<EventRelations[K]>) => {
    void Promise.resolve().then(request).then(result => {
      if (!cancelled) { state = { ...state, [key]: result }; publish(state); }
    }).catch((error: unknown) => {
      if (!cancelled) {
        state = { ...state, [key]: { ...empty('ERROR'), error: error instanceof Error ? error.message : '关联查询失败' } };
        publish(state);
      }
    });
  };
  load('collaboration', async () => {
    const result = await sources.collaboration(eventId);
    const value = page(result.runs, result.total, x => x.run_id);
    if (result.eventId !== eventId || value.items.some(x => objectValue(x.normalized_event).eventId !== eventId)) {
      throw new Error('研判事件关联无法确认');
    }
    return value;
  });
  load('plan', async () => {
    const result = await sources.plan(eventId);
    const value = page<EventPlan>(result.plans, result.total, x => x.planId);
    if (value.items.some(x => x.eventId !== eventId)) throw new Error('方案事件关联无法确认');
    const selected = newest(value.items, x => x.updatedAt || x.createdAt);
    if (selected) {
      const detail = await sources.planDetail(selected.planId);
      if (detail.plan.eventId !== eventId || detail.plan.planId !== selected.planId || detail.definitionId !== selected.planId) {
        throw new Error('方案详情事件关联无法确认');
      }
      return { ...value, items: value.items.map(x => x.planId === selected.planId ? { ...x, detail: detail.plan } : x) };
    }
    return value;
  });
  // This DTO has no eventId; authority is the existing exact event_id API, never a global list.
  load('workflow', async () => {
    const result = await sources.workflow(eventId);
    return page(result.runs, result.total, x => x.runId);
  });
  return () => { cancelled = true; };
}

export type PrimaryActionKind = 'none' | 'retry' | 'analysis' | 'plan' | 'execute' | 'view_judgment' | 'view_plan' | 'view_workflow';
export interface PrimaryAction {
  kind: PrimaryActionKind;
  label: string;
  stage: string;
  creates: boolean;
  targetId?: string;
}
export function derivePrimaryAction(relations: EventRelations): PrimaryAction {
  const action = (kind: PrimaryActionKind, label: string, stage: string, targetId?: string): PrimaryAction =>
    ({ kind, label, stage, targetId, creates: ['analysis', 'plan', 'execute'].includes(kind) });
  if (!relations.eventId) return action('none', '请选择事件', '尚未选择事件');
  const states = [relations.collaboration, relations.plan, relations.workflow];
  if (states.some(x => x.status === 'ERROR')) return action('retry', '重试关联查询', '暂时无法确认当前处置阶段');
  if (states.some(x => x.status === 'LOADING' || x.status === 'IDLE')) return action('none', '正在确认处置阶段', '关联信息加载中');
  const run = currentWorkflow(relations);
  if (run) {
    const labels: Record<string, [string, string]> = {
      awaiting_approval: ['去审批', '等待人工确认'], completed: ['查看执行结果', '执行已完成'],
      rejected: ['查看驳回原因', '执行已驳回'], failed: ['查看失败详情', '执行失败'],
      cancelled: ['查看取消记录', '执行已取消'], running: ['查看执行进展', '执行中'],
      paused: ['查看执行进展', '执行已暂停'], pending: ['查看执行进展', '待执行'],
    };
    const [label, stage] = labels[run.status] || ['查看执行记录', '执行状态待确认'];
    return action('view_workflow', label, stage, run.runId);
  }
  const plan = currentPlan(relations);
  if (plan) {
    if (plan.detail?.definitionStatus !== 'active') return action('view_plan', '查看处置方案', '方案暂不可执行', plan.planId);
    return action('execute', '启动执行', '处置方案已生成', plan.planId);
  }
  const judgment = currentCollaboration(relations);
  if (judgment) {
    if (['completed', 'partial_success'].includes(judgment.status)) return action('plan', '生成处置方案', '研判已完成', judgment.run_id);
    if (judgment.status === 'failed') return action('analysis', '重新研判', '研判失败');
    const stage = ({ pending: '待研判', running: '研判中', routing: '研判中', arbitrating: '研判中', fusing: '研判中', interrupted: '研判已中断', cancelled: '研判已取消' } as Record<string, string>)[judgment.status] || '研判状态未记录';
    return action('view_judgment', '查看研判', stage, judgment.session_id);
  }
  return action('analysis', '开始研判', '尚未研判');
}

export function eventSourceLabel(payload: unknown): string {
  const top = objectValue(payload);
  const raw = objectValue(top.rawEvent);
  const full = objectValue(top.fullResult);
  const provenances = [top.provenance, raw.provenance, full.provenance, objectValue(full.standardEvent).provenance].map(objectValue);
  const sources = provenances.map(p => String(p.sourceType || ''));
  if (sources.some(s => ['synthetic_validation', 'synthetic_validation_holdout', 'synthetic_event_system_closure', 'synthetic_case_seed'].includes(s))) return '合成验证事件';
  // No production provenance contract is currently defined; persistence alone is not verification.
  return '来源未核验';
}
