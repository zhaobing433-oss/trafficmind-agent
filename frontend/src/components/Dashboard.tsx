/**
 * Dashboard — 智慧交通指挥中心大屏主布局
 * CSS Grid 深色主题，单页全屏
 */

import { useState } from 'react';
import { Spin, Alert } from 'antd';
import { useDashboardData } from '../hooks/useDashboardData';
import type { EventRecord, AnalyzeResult } from '../types';
import Header from './Header';
import StatisticsCards from './StatisticsCards';
import RiskPieChart from './RiskPieChart';
import EventTypeBarChart from './EventTypeBarChart';
import TrendLineChart from './TrendLineChart';
import EventList from './EventList';
import EventFeed from './EventFeed';
import EventDetailModal from './EventDetailModal';
import EventFormModal from './EventFormModal';

export default function Dashboard() {
  const { stats, events, loading, error, refresh } = useDashboardData();

  const [detailModal, setDetailModal] = useState<{ open: boolean; event: EventRecord | null }>({
    open: false,
    event: null,
  });
  const [detailData, setDetailData] = useState<AnalyzeResult | null>(null);
  const [formModalOpen, setFormModalOpen] = useState(false);

  if (loading && !stats) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="正在加载指挥中心数据…">
          <div style={{ height: 120 }} />
        </Spin>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #0a0e27 0%, #0d1235 50%, #0f1545 100%)',
      padding: '0 24px 24px',
      color: '#e0e0e0',
    }}>
      {/* 顶部标题栏 */}
      <Header
        onNewEvent={() => setFormModalOpen(true)}
        onRefresh={refresh}
        loading={loading}
      />

      {error && (
        <Alert message={error} type="error" showIcon closable style={{ marginBottom: 16 }} />
      )}

      {/* 统计卡片行 */}
      <StatisticsCards stats={stats} />

      {/* 图表行：三个图表并排 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 16,
        marginBottom: 16,
      }}>
        <RiskPieChart distribution={stats?.riskDistribution || []} />
        <EventTypeBarChart distribution={stats?.eventTypeDistribution || []} />
        <TrendLineChart trend={stats?.dailyTrend || []} />
      </div>

      {/* 底部：事件列表 + 动态推送 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '2fr 1fr',
        gap: 16,
      }}>
        <EventList
          events={events}
          onRowClick={async (event) => {
            setDetailModal({ open: true, event });
            try {
              const { getEventById } = await import('../api');
              const data = await getEventById(event.eventId);
              setDetailData(data);
            } catch {
              setDetailData(null);
            }
          }}
          onStatusChange={refresh}
        />
        <EventFeed events={events} />
      </div>

      {/* 弹窗 */}
      <EventDetailModal
        open={detailModal.open}
        event={detailModal.event}
        detailData={detailData}
        onClose={() => setDetailModal({ open: false, event: null })}
      />
      <EventFormModal
        open={formModalOpen}
        onClose={() => setFormModalOpen(false)}
        onSuccess={refresh}
      />
    </div>
  );
}
