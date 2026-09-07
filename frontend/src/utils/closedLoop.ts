import type { PlanDetail, PlanDetailResponse, PlanStep, PlanListResponse } from '../types/planning';
import type { WorkflowRunDetail } from '../api/workflowApi';
import { record, text } from './judgment';

export const executionStatus = (status: unknown): string => ({
  pending: '待执行', running: '执行中', paused: '已暂停', awaiting_approval: '等待人工审批',
  completed: '流程已完成', rejected: '已驳回', failed: '执行失败', cancelled: '已取消',
} as Record<string, string>)[text(status)] || '状态未记录';
export const terminalExecution = (status: unknown) => ['completed', 'rejected', 'failed', 'cancelled'].includes(text(status));
export const closureRecordNotice = (status: unknown) => terminalExecution(status)
  ? '本次流程已结束；尚无法确认是否形成历史处置记录。实际交通处置效果未记录。' : '流程尚未结束';

export function validatePlan(detail: PlanDetailResponse, planId: string, eventId?: string): PlanDetailResponse {
  if (detail.plan?.planId !== planId || detail.definitionId !== planId || (eventId && detail.plan.eventId !== eventId)) throw new Error('方案关联不匹配，无法确认当前闭环状态');
  return detail;
}
export function planSource(plan: PlanDetail) {
  const source = plan.metadata?.sourceAgent;
  return source?.sessionId && source.collaborationRunId
    ? { sessionId: source.sessionId, runId: source.collaborationRunId, eventId: plan.eventId || undefined } : null;
}
export function validateWorkflow(detail: WorkflowRunDetail, runId: string): WorkflowRunDetail {
  if (detail.run?.runId !== runId || (detail.state?.workflowRunId && detail.state.workflowRunId !== runId)) throw new Error('执行记录不匹配，未显示其它流程');
  return detail;
}
export function exactPendingApproval(detail: WorkflowRunDetail, runId: string, approvalId?: string) {
  validateWorkflow(detail, runId);
  const approval = record(detail.state.pendingApproval);
  if (detail.run.status !== 'awaiting_approval' || approval.workflowRunId !== runId || approval.decision !== 'pending'
    || !text(approval.approvalId) || (approvalId && approval.approvalId !== approvalId)) throw new Error('待审批操作已变化，请刷新后确认');
  return approval;
}

export async function workflowSourcePlan(detail: WorkflowRunDetail, get: (id: string) => Promise<PlanDetailResponse>): Promise<PlanDetail | null> {
  const id = text(detail.run.definitionId);
  if (!id) return null;
  let response: PlanDetailResponse;
  try { response = await get(id); } catch (error) {
    if (error instanceof Error && /get plan failed: 400$/.test(error.message)) return null;
    throw error;
  }
  return validatePlan(response, id, text(record(detail.state.currentEvent).eventId) || undefined).plan;
}

// Every page and detail is checked; a query failure is never a missing-plan result.
export async function judgmentPlans(eventId: string, sessionId: string, runId: string, sources: {
  list: (params: { eventId: string; page: number; pageSize: number }) => Promise<PlanListResponse>;
  detail: (id: string) => Promise<PlanDetailResponse>;
}): Promise<PlanDetail[]> {
  const plans: PlanDetail[] = [], seen = new Set<string>();
  let total: number | undefined;
  for (let page = 1; ; page++) {
    const data = await sources.list({ eventId, page, pageSize: 50 });
    if (!Array.isArray(data.plans) || !Number.isInteger(data.total) || data.total < 0 || (total !== undefined && total !== data.total)) throw new Error('方案列表已变化，请重新加载');
    total = data.total;
    for (const item of data.plans) {
      if (item.eventId !== eventId || !item.planId || seen.has(item.planId)) throw new Error('方案事件关联无法确认');
      seen.add(item.planId);
      const detail = validatePlan(await sources.detail(item.planId), item.planId, eventId);
      const source = planSource(detail.plan);
      if (source?.sessionId === sessionId && source.runId === runId) plans.push(detail.plan);
    }
    if (seen.size === total) return plans;
    if (!data.plans.length || seen.size > total) throw new Error('方案列表不完整，无法确认当前闭环状态');
  }
}

export function loadClosedLoopSelection<T>(request: () => Promise<T>, receive: (value: T) => void, fail: (message: string) => void): () => void {
  let active = true;
  request().then(value => { if (active) receive(value); }).catch(error => { if (active) fail(error instanceof Error ? error.message : '关系加载失败'); });
  return () => { active = false; };
}

const stepNames: Record<string, string> = { validate_event: '核验交通事件', rule_router: '核对处置规则', rag_retrieve: '检索规则知识', memory_context: '读取历史上下文', agent_task: '研判分析', evidence_evaluate: '评估依据', risk_gate: '风险检查', human_approval: '人工审批', action: '执行操作', wait: '等待', monitor: '观察执行情况', close: '结束流程' };
const actionNames: Record<string, string> = { notify_dingtalk: '发送调度通知', create_work_order: '创建处置工单', dispatch: '调度处置', dispatch_notify: '通知处置人员', notify: '发送通知', notify_dispatch: '通知调度', adjust_signal: '调整信号', signal_control: '信号控制', traffic_control: '交通管控', save_result: '保存记录', publish_warning: '发布预警' };
export const actionName = (action: Record<string, unknown>) => text(action.description) || text(action.summary) || actionNames[text(action.actionType || action.action_type)] || '操作名称未记录';
export const stepName = (step: PlanStep) => text(step.objective) || stepNames[text(step.stepType)] || '操作名称未记录';
export const stepState = (value: unknown) => ({ pending: '待执行', ready: '具备执行条件', running: '执行中', awaiting_approval: '等待人工审批', succeeded: '步骤已完成', failed: '执行失败', denied: '不可执行', skipped: '已跳过', cancelled: '已取消', blocked: '已阻断' } as Record<string, string>)[text(value)] || '执行状态未记录';
