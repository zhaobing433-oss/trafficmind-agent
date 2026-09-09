import { useEffect, useState } from 'react';
import { getPlan, listPlans } from '../../api/planningApi';
import type { PlanDetail } from '../../types/planning';
import { judgmentPlans, loadClosedLoopSelection } from '../../utils/closedLoop';
import '../workflow/execution.css';

export function JudgmentPlanLink({ eventId, sessionId, runId, onOpenPlan }: { eventId?: string; sessionId: string; runId: string; onOpenPlan?: (id: string) => void }) {
  const [result, setResult] = useState<{ key: string; plans?: PlanDetail[]; error?: string } | null>(null);
  const [revision, setRevision] = useState(0), key = JSON.stringify([eventId, sessionId, runId, revision]);
  useEffect(() => {
    if (!eventId) return;
    return loadClosedLoopSelection(() => judgmentPlans(eventId, sessionId, runId, { list: listPlans, detail: getPlan }),
      plans => setResult({ key, plans }), error => setResult({ key, error }));
  }, [key]);
  if (!eventId) return <p className="execution-muted">未关联事件，无法确认来源处置方案。</p>;
  return <section className="execution-section" aria-label="本次研判的处置方案"><h3>处置方案</h3>
    {result?.key !== key ? <p>正在核对本次研判的方案...</p> : result.error ? <p role="alert">无法确认当前闭环状态：{result.error} <button onClick={() => setRevision(x => x + 1)}>重新加载</button></p>
      : !result.plans?.length ? <p className="execution-muted">本次研判尚未生成处置方案</p>
      : result.plans.map(plan => <div className="execution-source" key={plan.planId}><span>已生成处置方案：{plan.goal || '未命名方案'}</span>{onOpenPlan && <button className="execution-link" onClick={() => onOpenPlan(plan.planId)}>查看处置方案</button>}</div>)}
  </section>;
}
