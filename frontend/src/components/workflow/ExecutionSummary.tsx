import type { WorkflowRunDetail } from '../../api/workflowApi';
import type { PlanDetail } from '../../types/planning';
import { closureRecordNotice, executionStatus, planSource, stepName, stepState, terminalExecution } from '../../utils/closedLoop';
import { judgmentTitle, record, text } from '../../utils/judgment';
import { PlanSourceContext, LinkedEventName } from '../planning/PlanSourceContext';
import './execution.css';
import { formatDateTime } from '../../utils/format';

export function ExecutionSummary({ detail, plan, onOpenPlan, onOpenJudgment }: { detail: WorkflowRunDetail; plan: PlanDetail | null; onOpenPlan?: (id: string) => void; onOpenJudgment?: (sid: string, rid: string, eid?: string) => void }) {
  const event = record(detail.state.currentEvent), source = plan && planSource(plan);
  const status = text(detail.run.status), current = detail.nodeRuns.find(node => node.nodeId === detail.run.currentNodeId);
  return <section className="execution-section" aria-label="当前处置执行">
    <h2 style={{ fontSize: 19, margin: '0 0 8px' }}>{text(event.eventId) ? judgmentTitle(event) : '处置执行'}</h2>
    <div className="execution-source"><strong>{executionStatus(status)}</strong><span className="execution-muted">最近更新：{detail.run.updatedAt ? formatDateTime(text(detail.run.updatedAt)) : '未记录'}</span></div>
    <div className="execution-source">关联事件：{text(event.eventId) ? judgmentTitle(event) : <LinkedEventName eventId={plan?.eventId} />}</div>
    <div className="execution-source">来源处置方案：{plan ? plan.goal || '未命名方案' : '未关联处置方案'}{plan && onOpenPlan && <button className="execution-link" onClick={() => onOpenPlan(plan.planId)}>查看来源方案</button>}</div>
    {plan && <PlanSourceContext plan={plan} onOpenJudgment={onOpenJudgment} />}
    <ol className="execution-progress" aria-label="处置闭环">
      <li><strong>事件发现</strong><span>{text(event.eventId) || plan?.eventId ? '已关联事件' : '未关联'}</span></li>
      <li><strong>AI 研判</strong><span>{source ? '已关联来源研判' : '未记录'}</span></li>
      <li><strong>生成方案</strong><span>{plan ? '已生成处置方案' : '未关联'}</span></li>
      <li><strong>执行处置</strong><span>{executionStatus(status)}</span></li>
    </ol>
    <p>当前步骤：{terminalExecution(status) ? '本次流程已结束' : current ? stepName({ stepType: text(current.nodeType) }) : '未记录'}</p>
    {detail.nodeRuns.length > 0 && <details><summary>执行步骤记录（{detail.nodeRuns.length}）</summary>{detail.nodeRuns.map((node, i) => <div className="execution-step" key={text(node.id) || i}>{i + 1}. {stepName({ stepType: text(node.nodeType) })} · {stepState(node.status)}<span className="execution-muted"> · {text(node.completedAt) || text(node.startedAt) || '时间未记录'}</span></div>)}</details>}
    {terminalExecution(status) && <p className="execution-muted" aria-label="本次处置记录">{closureRecordNotice(status)}</p>}
  </section>;
}
