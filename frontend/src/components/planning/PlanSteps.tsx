import type { PlanDetail, PlanRunSummary } from '../../types/planning';
import { actionName, stepName, stepState, terminalExecution, executionStatus } from '../../utils/closedLoop';
import { text } from '../../utils/judgment';

export function PlanSteps({ plan, run }: { plan: PlanDetail; run?: PlanRunSummary | null }) {
  const rejected = plan.metadata?.agentRecommendationAudit?.rejected || [];
  const ended = run?.version === plan.version && terminalExecution(run?.status);
  return <section className="execution-section" aria-label="处置步骤"><h3>处置步骤</h3>
    {ended && <p className="execution-muted">{executionStatus(run?.status)}，不继续执行。以下为已记录步骤，不表示允许执行后续操作。</p>}
    {!plan.steps?.length && <p className="execution-muted">方案步骤未记录</p>}
    {plan.steps?.map((step, index) => <div className="execution-step" key={step.stepId || index}>
      <div className="execution-step-heading"><strong>{index + 1}. {stepName(step)}</strong><span className="execution-badge">{ended && ['ready', 'pending', 'running', 'awaiting_approval'].includes(run?.stepStatuses?.[step.stepId || ''] || '') ? '流程已结束，不继续执行' : run?.version === plan.version ? stepState(run.stepStatuses?.[step.stepId || '']) : '执行状态未记录'}</span><span>{step.approvalRequired === true ? '需要人工审批' : step.approvalRequired === false ? '无需人工审批' : '审批要求未记录'}</span></div>
      {ended && <details className="execution-muted"><summary>步骤状态记录</summary>{stepState(run?.stepStatuses?.[step.stepId || ''])}（流程结束时的记录）</details>}
      <div className="execution-muted">预期结果：{step.expectedOutcome || '未记录'}</div>
      {step.preconditions?.length ? <div className="execution-muted">执行条件：{step.preconditions.join('；')}</div> : null}
    </div>)}
    {rejected.length > 0 && <details><summary>未纳入执行的建议（{rejected.length}）</summary>{rejected.map((item, index) => <p key={index}>{actionName(item)} · 不可执行 / 未支持<span className="execution-muted">（{({ unsupported_action: '当前不支持此操作', not_registered: '操作未注册', simulation_only: '仅限内部演练', invalid_structure: '参数不完整' } as Record<string, string>)[text(item.reason)] || '原因未记录'}）</span></p>)}</details>}
  </section>;
}
