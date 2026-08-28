import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import ChatWorkspace from '../ChatWorkspace';
import { getDailyReport, getHighRiskRoads, getStats } from '../../api/index';
import type { DailyReportResponse, HighRiskRoad, StatsResponse } from '../../types/index';

interface ReportDashboardProps {
  onOpenRoad: (roadName: string) => void;
  onOpenRisk: (risk: string) => void;
}

export function ReportDashboard({ onOpenRoad, onOpenRisk }: ReportDashboardProps) {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [roads, setRoads] = useState<HighRiskRoad[]>([]);
  const [daily, setDaily] = useState<DailyReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [statsResult, roadsResult, dailyResult] = await Promise.allSettled([
      getStats(),
      getHighRiskRoads(10, 30, '高风险'),
      getDailyReport(),
    ]);

    const failures: string[] = [];
    if (statsResult.status === 'fulfilled') setStats(statsResult.value);
    else failures.push('统计数据');
    if (roadsResult.status === 'fulfilled') setRoads(roadsResult.value.topRoads || []);
    else failures.push('高风险路口');
    if (dailyResult.status === 'fulfilled') setDaily(dailyResult.value);
    else failures.push('日报');

    setError(failures.length ? `${failures.join('、')}加载失败` : null);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const typeDist = stats?.eventTypeDistribution || [];
  const riskDist = stats?.riskDistribution || [];
  const findings = daily?.keyFindings || [];
  const suggestions = daily?.suggestions || [];
  const maxTypeCount = useMemo(() => Math.max(1, ...typeDist.map(d => Number(d.count) || 0)), [typeDist]);

  const metrics = [
    { label: '总事件数', value: valueOrDash(stats?.totalEvents), color: '#0F766E', click: null },
    { label: '高风险', value: valueOrDash(stats?.highRiskCount), color: '#DC2626', click: '高风险' },
    { label: '待处置', value: valueOrDash(stats?.pendingDispatch), color: '#D97706', click: null },
    { label: '平均风险分', value: valueOrDash(stats?.avgRiskScore), color: '#2563EB', click: null },
  ];

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <header>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>统计报告</h2>
        <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>日报/周报 · 高风险路口 · 事件趋势 · 管理建议</p>
      </header>

      {error && (
        <div style={errorBannerStyle}>
          <span>{error}，已保留可读取的数据。</span>
          <button onClick={load} style={smallButtonStyle}>重试</button>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        {metrics.map(x => (
          <button key={x.label}
            onClick={x.click ? () => onOpenRisk(x.click) : undefined}
            disabled={!x.click}
            title={x.click ? '跳转交通态势并按风险等级过滤' : undefined}
            style={{
              ...metricCardStyle,
              cursor: x.click ? 'pointer' : 'default',
              textAlign: 'left',
            }}>
            <div style={{ fontSize: 11, color: '#9CA3AF' }}>
              {x.label}{x.click && <span style={{ marginLeft: 6, color: '#2563EB' }}>查看</span>}
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, color: x.color }}>{loading && !stats ? '...' : x.value}</div>
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
        <section style={panelStyle}>
          <div style={sectionTitleStyle}>事件类型分布</div>
          {loading && !stats ? <EmptyText text="正在加载事件分布..." />
          : typeDist.length === 0 ? <EmptyText text="暂无事件类型数据" />
          : typeDist.map((t, i) => (
            <div key={`${t.type}-${i}`} style={barRowStyle}>
              <span style={{ flex: 1, minWidth: 72 }}>{t.type || '未记录'}</span>
              <div style={barTrackStyle}>
                <div style={{ height: '100%', width: `${Math.min(100, ((Number(t.count) || 0) / maxTypeCount) * 100)}%`, background: '#0F766E', borderRadius: 4 }} />
              </div>
              <span style={{ color: '#6B7280', minWidth: 30, textAlign: 'right' }}>{t.count}</span>
            </div>
          ))}
        </section>

        <section style={panelStyle}>
          <div style={sectionTitleStyle}>风险等级分布</div>
          {loading && !stats ? <EmptyText text="正在加载风险分布..." />
          : riskDist.length === 0 ? <EmptyText text="暂无风险等级数据" />
          : riskDist.map((r, i) => (
            <button key={`${r.level}-${i}`} onClick={() => r.level && onOpenRisk(r.level)}
              title={r.level ? '跳转交通态势并按风险等级过滤' : undefined}
              style={riskRowStyle}>
              <span style={{ flex: 1 }}>{r.level || '未记录'}</span>
              <span style={{ fontWeight: 600 }}>{r.count}</span>
              <span style={{ color: '#2563EB', fontSize: 11 }}>查看</span>
            </button>
          ))}
        </section>
      </div>

      <section style={panelStyle}>
        <div style={sectionHeaderStyle}>
          <div style={sectionTitleStyle}>高风险路口</div>
          <span style={{ fontSize: 11, color: '#9CA3AF' }}>最近 30 天 · {roads.length} 条</span>
        </div>
        {loading && roads.length === 0 ? <EmptyText text="正在加载高风险路口..." />
        : roads.length === 0 ? <EmptyText text="暂无高风险路口数据" />
        : roads.slice(0, 5).map((r, i) => (
          <div key={`${r.roadName}-${i}`} style={roadRowStyle}>
            <div style={{ flex: '1 1 220px', minWidth: 0 }}>
              <strong>{r.roadName || '未记录路段'}</strong>
              <span style={{ color: '#6B7280' }}> · {r.totalEvents} 起 · 均分 {r.avgRiskScore} · 最常见 {r.mostCommonEventType || '未记录'}</span>
              <div style={{ color: '#6B7280', fontSize: 11, marginTop: 2 }}>{(r.suggestedAction || '暂无管理建议').slice(0, 120)}</div>
            </div>
            {r.roadName && (
              <button onClick={() => onOpenRoad(r.roadName)} style={blueButtonStyle}>查看该路段事件</button>
            )}
          </div>
        ))}
      </section>

      {(findings.length > 0 || suggestions.length > 0) && (
        <section style={panelStyle}>
          <div style={sectionTitleStyle}>管理建议</div>
          {findings.map((f, i) => <div key={`f-${i}`} style={findingStyle}>{f}</div>)}
          {suggestions.map((s, i) => <div key={`s-${i}`} style={suggestionStyle}>{s}</div>)}
        </section>
      )}

      <div>
        <ChatWorkspace
          sessionId={undefined}
          pendingCreate={true}
          defaultMode="report"
          showFullModes={false}
          onSessionCreated={() => {}}
          onConversationUpdate={() => {}}
          onNewConversation={() => {}}
          view="report"
        />
      </div>
    </div>
  );
}

function valueOrDash(v: number | null | undefined): string {
  return v === null || v === undefined ? '-' : String(v);
}

function EmptyText({ text }: { text: string }) {
  return <div style={{ fontSize: 12, color: '#9CA3AF', padding: '8px 0' }}>{text}</div>;
}

const panelStyle: CSSProperties = {
  background: '#FFF',
  borderRadius: 8,
  padding: 14,
  border: '1px solid #E5E7EB',
};

const metricCardStyle: CSSProperties = {
  background: '#FFF',
  borderRadius: 8,
  padding: '12px 16px',
  border: '1px solid #E5E7EB',
};

const sectionTitleStyle: CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  marginBottom: 8,
  color: '#111827',
};

const sectionHeaderStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
};

const barRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  marginBottom: 5,
  fontSize: 12,
};

const barTrackStyle: CSSProperties = {
  flex: 2,
  minWidth: 90,
  height: 8,
  borderRadius: 4,
  background: '#F3F4F6',
  overflow: 'hidden',
};

const riskRowStyle: CSSProperties = {
  display: 'flex',
  width: '100%',
  gap: 8,
  marginBottom: 4,
  fontSize: 12,
  border: 'none',
  background: 'transparent',
  padding: '4px 0',
  cursor: 'pointer',
  textAlign: 'left',
  color: '#374151',
};

const roadRowStyle: CSSProperties = {
  padding: '8px 0',
  borderBottom: '1px solid #F3F4F6',
  fontSize: 12,
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  gap: 8,
  flexWrap: 'wrap',
};

const blueButtonStyle: CSSProperties = {
  padding: '4px 10px',
  borderRadius: 6,
  border: '1px solid #BFDBFE',
  background: '#EFF6FF',
  color: '#2563EB',
  cursor: 'pointer',
  fontSize: 11,
  flexShrink: 0,
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

const findingStyle: CSSProperties = {
  fontSize: 12,
  color: '#374151',
  padding: '2px 0',
};

const suggestionStyle: CSSProperties = {
  fontSize: 12,
  color: '#0F766E',
  padding: '2px 0',
  fontWeight: 500,
};
