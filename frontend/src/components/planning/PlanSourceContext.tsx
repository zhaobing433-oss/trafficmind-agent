import { useEffect, useState } from 'react';
import { getEventById } from '../../api/index';
import { collabApi } from '../../api/collaborationApi';
import type { PlanDetail } from '../../types/planning';
import { judgmentTitle, record, text } from '../../utils/judgment';
import { loadClosedLoopSelection, planSource } from '../../utils/closedLoop';
import { validateJudgmentDetail } from '../../utils/judgmentQuery';
import { formatDateTime } from '../../utils/format';

export function LinkedEventName({ eventId }: { eventId?: string | null }) {
  const [result, setResult] = useState<{ id: string; title: string } | null>(null);
  useEffect(() => {
    if (!eventId) return;
    return loadClosedLoopSelection(async () => {
      const top = record(await getEventById(encodeURIComponent(eventId)));
      const standard = record(top.standardEvent), full = record(record(top.fullResult).standardEvent);
      const id = text(top.eventId) || text(standard.eventId) || text(full.eventId);
      if (id !== eventId) throw new Error('事件不匹配');
      return judgmentTitle({ roadName: text(top.roadName) || text(standard.roadName) || text(full.roadName),
        eventTypeCn: text(top.eventTypeCn) || text(top.eventType) || text(standard.eventTypeCn) || text(standard.eventType) || text(full.eventTypeCn) || text(full.eventType) });
    }, title => setResult({ id: eventId, title }), () => setResult({ id: eventId, title: '关联事件信息暂不可用' }));
  }, [eventId]);
  return <span>{!eventId ? '未关联事件' : result?.id === eventId ? result.title : '正在加载关联事件...'}</span>;
}

export function PlanSourceContext({ plan, onOpenJudgment }: { plan: PlanDetail; onOpenJudgment?: (sessionId: string, runId: string, eventId?: string) => void }) {
  const source = planSource(plan), key = JSON.stringify(source);
  const [result, setResult] = useState<{ key: string; error?: string; time?: string } | null>(null);
  useEffect(() => {
    if (!source) return;
    return loadClosedLoopSelection(async () => {
      const detail = await collabApi.getRun(source.runId);
      validateJudgmentDetail(detail, source);
      return text(detail.run.started_at);
    }, time => setResult({ key, time }), error => setResult({ key, error }));
  }, [key]);
  const ready = result?.key === key;
  return <div className="execution-source" aria-label="来源研判">
    <span>来源研判：{!source ? '未记录来源研判' : !ready ? '正在核对...' : result.error ? '来源研判暂不可用' : result.time ? `${formatDateTime(result.time)} 的研判` : '已关联本次方案的研判（时间未记录）'}</span>
    {source && ready && !result.error && onOpenJudgment && <button className="execution-link" onClick={() => onOpenJudgment(source.sessionId, source.runId, source.eventId)}>查看来源研判</button>}
  </div>;
}
