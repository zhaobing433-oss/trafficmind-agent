import type { RecentJudgments as RecentJudgmentsData } from '../../types/judgment';
import { STATUS_LABELS } from '../../types/collaboration';
import './judgment.css';

export interface RecentJudgmentProps {
  judgments: RecentJudgmentsData;
  judgmentsLoading: boolean;
  judgmentsError: string | null;
  onOpenJudgment: (sessionId: string, runId?: string, eventId?: string) => void;
  onRecentClick: (id: string) => void;
}

export default function RecentJudgments({ judgments, judgmentsLoading, judgmentsError, onOpenJudgment, onRecentClick }: RecentJudgmentProps) {
  if (judgmentsLoading) return <p className="judgment-muted">正在加载最近研判...</p>;
  if (judgmentsError) return <p className="judgment-muted" role="alert">{judgmentsError}</p>;
  return <div aria-label="按事件聚合的最近研判">
    <p className="judgment-muted">已加载最近 {judgments.sessionsLoaded} 个会话内的记录</p>
    {judgments.events.map(item => <button key={item.eventId} className="recent-judgment" data-recent-event={item.eventId}
      onClick={() => onOpenJudgment(item.latestSessionId, item.latestRunId, item.eventId)}>
      <strong>{item.businessTitle}</strong>
      <small>{item.lastJudgedAt ? new Date(item.lastJudgedAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '研判时间未记录'}</small>
      <small>已加载 {item.judgmentLoaded} 次研判 · {STATUS_LABELS[item.latestStatus] || '状态未记录'}</small>
    </button>)}
    {judgments.legacy.length > 0 && <details style={{ marginTop: 10, fontSize: 12 }}><summary>历史研判（未关联事件）</summary>
      <p className="judgment-muted">这些历史研判缺少可靠的事件关联信息，因此未合并到最近研判中。</p>
      {judgments.legacy.map(session => <button key={session.id} className="recent-judgment" onClick={() => session.unboundRunId
        ? onOpenJudgment(session.id, session.unboundRunId) : onRecentClick(session.id)}>
        <strong>{session.title || '未命名研判'}</strong><small>未记录事件关联</small>
      </button>)}
    </details>}
    {judgments.failedSessions.length > 0 && <p className="judgment-muted" role="alert">{judgments.failedSessions.length} 个会话的研判记录未能加载，关联情况未知</p>}
  </div>;
}
