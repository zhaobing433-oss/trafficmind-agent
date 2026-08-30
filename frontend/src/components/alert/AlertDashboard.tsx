import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { getHighRiskRoads, getUnclosedAlerts } from '../../api/index';
import type { AlertItem, HighRiskRoad } from '../../types/index';
import { RelatedWorkflowRuns } from '../workflow/RelatedWorkflowRuns';
import { eventTitle, isIncompleteEvent } from '../../utils/display';

interface AlertDashboardProps {
  onOpenEvent: (eventId: string) => void;
  onOpenRoad: (roadName: string) => void;
  onOpenRun: (runId: string) => void;
}

export function AlertDashboard({ onOpenEvent, onOpenRoad, onOpenRun }: AlertDashboardProps) {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [roads, setRoads] = useState<HighRiskRoad[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [alertsResult, roadsResult] = await Promise.allSettled([
      getUnclosedAlerts(720),
      getHighRiskRoads(10, 30, '高风险'),
    ]);

    const failures: string[] = [];
    if (alertsResult.status === 'fulfilled') setAlerts(alertsResult.value.alerts || []);
    else failures.push('未闭环事件');
    if (roadsResult.status === 'fulfilled') setRoads(roadsResult.value.topRoads || []);
    else failures.push('高风险路口');

    setError(failures.length ? `${failures.join('、')}加载失败` : null);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <header>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>风险提醒</h2>
        <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>未闭环事件 · 高风险路口 · 真实事件关联</p>
      </header>

      {error && (
        <div style={errorBannerStyle}>
          <span>{error}，已保留可读取的数据。</span>
          <button onClick={load} style={smallButtonStyle}>重试</button>
        </div>
      )}

      <section style={panelStyle}>
        <div style={{ fontSize: 13, color: '#6B7280', lineHeight: 1.7, marginBottom: 12 }}>
          未闭环事件指已被系统发现和研判，但尚未完成处置闭环的交通事件。系统内状态仅代表本工作台记录，不代表已接入真实交管派单系统。
        </div>
        <div style={sectionHeaderStyle}>
          <h3 style={sectionTitleStyle}>未闭环列表</h3>
          <span style={{ fontSize: 11, color: '#9CA3AF' }}>{alerts.length} 条</span>
        </div>

        {loading && alerts.length === 0 ? <EmptyText text="正在加载未闭环事件..." />
        : alerts.length === 0 ? <EmptyText text="当前没有未闭环事件" />
        : alerts.slice(0, 10).map((a, i) => {
          const eventId = a.eventId || '';
          const expanded = expandedEvent === eventId && Boolean(eventId);
          const title = eventTitle({ roadName: a.roadName, eventType: a.eventType }, '未知来源事件');
          const incomplete = isIncompleteEvent({ roadName: a.roadName, eventType: a.eventType });
          return (
            <div key={`${eventId}-${i}`} style={alertRowStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <strong style={{ fontSize: 13, color: '#111827' }}>{title}</strong>
                <span style={{ color: riskColor(a.riskLevel), fontWeight: 600 }}>{a.riskLevel || '未记录风险'}</span>
                <span style={{ color: '#6B7280' }}>{a.status || '状态未记录'}</span>
                <span style={{ color: '#9CA3AF' }}>已持续 {a.durationSinceCreated || '未记录'}</span>
                {incomplete && <span style={{ color: '#D97706' }}>信息不完整</span>}
                {eventId && (
                  <button onClick={() => onOpenEvent(eventId)} style={blueButtonStyle}>查看事件</button>
                )}
                {eventId && (
                  <button onClick={() => setExpandedEvent(expanded ? null : eventId)} style={greenButtonStyle}>
                    {expanded ? '收起相关运行' : '相关运行'}
                  </button>
                )}
              </div>
              {eventId && <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 3, fontFamily: 'monospace' }}>事件编号 {eventId}</div>}
              {a.alertReason && <div style={{ fontSize: 11, color: '#6B7280', marginTop: 4 }}>{a.alertReason}</div>}
              {expanded && <RelatedWorkflowRuns eventId={eventId} onOpenRun={onOpenRun} />}
            </div>
          );
        })}
      </section>

      <section style={panelStyle}>
        <div style={sectionHeaderStyle}>
          <h3 style={{ ...sectionTitleStyle, color: '#0F766E' }}>高风险路口</h3>
          <span style={{ fontSize: 11, color: '#9CA3AF' }}>最近 30 天 · {roads.length} 条</span>
        </div>
        {loading && roads.length === 0 ? <EmptyText text="正在加载高风险路口..." />
        : roads.length === 0 ? <EmptyText text="暂无高风险路口数据" />
        : roads.map((r, i) => (
          <div key={`${r.roadName}-${i}`} style={roadRowStyle}>
            <span style={{ minWidth: 0 }}>
              <strong>{r.roadName || '未记录路段'}</strong>
              <span style={{ color: '#6B7280' }}> · {r.totalEvents} 起 · 均分 {r.avgRiskScore}</span>
            </span>
            {r.roadName && (
              <button onClick={() => onOpenRoad(r.roadName)} style={blueButtonStyle}>查看该路段事件</button>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}

function EmptyText({ text }: { text: string }) {
  return <div style={{ fontSize: 12, color: '#9CA3AF', padding: '8px 0' }}>{text}</div>;
}

function riskColor(level?: string | null): string {
  if (level === '重大风险') return '#B91C1C';
  if (level === '高风险') return '#DC2626';
  if (level === '中风险') return '#D97706';
  return '#6B7280';
}

const panelStyle: CSSProperties = {
  background: '#FFF',
  borderRadius: 8,
  padding: 16,
  border: '1px solid #E5E7EB',
};

const sectionHeaderStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
};

const sectionTitleStyle: CSSProperties = {
  fontSize: 15,
  fontWeight: 600,
  margin: 0,
  color: '#DC2626',
};

const alertRowStyle: CSSProperties = {
  padding: '8px 0',
  borderBottom: '1px solid #F3F4F6',
  fontSize: 12,
};

const roadRowStyle: CSSProperties = {
  padding: '8px 0',
  borderBottom: '1px solid #F3F4F6',
  fontSize: 12,
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
};

const smallButtonStyle: CSSProperties = {
  padding: '3px 10px',
  borderRadius: 6,
  border: '1px solid #E5E7EB',
  background: '#FFF',
  color: '#374151',
  cursor: 'pointer',
  fontSize: 11,
};

const blueButtonStyle: CSSProperties = {
  padding: '3px 10px',
  borderRadius: 6,
  border: '1px solid #BFDBFE',
  background: '#EFF6FF',
  color: '#2563EB',
  cursor: 'pointer',
  fontSize: 11,
  flexShrink: 0,
};

const greenButtonStyle: CSSProperties = {
  padding: '3px 10px',
  borderRadius: 6,
  border: '1px solid #99F6E4',
  background: '#F0FDFA',
  color: '#0F766E',
  cursor: 'pointer',
  fontSize: 11,
  flexShrink: 0,
};

const errorBannerStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 12,
  padding: '8px 12px',
  borderRadius: 8,
  background: '#FEF2F2',
  color: '#DC2626',
  border: '1px solid #FECACA',
  fontSize: 12,
};
