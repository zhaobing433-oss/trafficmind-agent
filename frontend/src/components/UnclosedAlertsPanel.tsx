/**
 * 未闭环事件提醒面板
 */
import { useState, useEffect } from 'react';
import { Card, Table, Tag, Button, Spin, Empty, message } from 'antd';
import { WarningOutlined, ReloadOutlined } from '@ant-design/icons';
import { getUnclosedAlerts } from '../api';
import type { AlertItem } from '../types';

const RISK_COLORS: Record<string, string> = {
  '低风险': 'green',
  '中风险': 'orange',
  '高风险': 'red',
  '重大风险': 'magenta',
};

const STATUS_COLORS: Record<string, string> = {
  '待研判': '#1677ff',
  '待派单': '#faad14',
  '处置中': '#52c41a',
  '待复盘': '#722ed1',
};

export default function UnclosedAlertsPanel() {
  const [loading, setLoading] = useState(false);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);

  const fetchAlerts = async () => {
    setLoading(true);
    try {
      const result = await getUnclosedAlerts(720, '低风险');
      setAlerts(result.alerts);
    } catch (e) {
      // 静默失败
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const timer = setInterval(fetchAlerts, 60000);
    return () => clearInterval(timer);
  }, []);

  const columns = [
    { title: '事件ID', dataIndex: 'eventId', key: 'eventId', width: 130 },
    { title: '类型', dataIndex: 'eventType', key: 'eventType', width: 70 },
    { title: '路段', dataIndex: 'roadName', key: 'roadName', ellipsis: true },
    {
      title: '风险', dataIndex: 'riskLevel', key: 'riskLevel', width: 70,
      render: (v: string) => <Tag color={RISK_COLORS[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 70,
      render: (v: string) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag>,
    },
    { title: '已持续', dataIndex: 'durationSinceCreated', key: 'duration', width: 80 },
    {
      title: '操作', key: 'action', width: 60,
      render: (_: unknown, record: AlertItem) => (
        <Button
          size="small"
          type="link"
          onClick={() => message.info(record.alertReason)}
        >
          详情
        </Button>
      ),
    },
  ];

  return (
    <Card
      title={<span><WarningOutlined style={{ color: '#faad14' }} /> 未闭环提醒</span>}
      size="small"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchAlerts} loading={loading} />}
      style={{ height: '100%', background: 'rgba(16,20,52,0.85)', borderColor: 'rgba(255,255,255,0.08)' }}
    >
      {loading && !alerts.length ? (
        <Spin />
      ) : alerts.length === 0 ? (
        <Empty description="所有事件已闭环" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div style={{ marginBottom: 8, color: '#faad14', fontWeight: 'bold' }}>
            共 {alerts.length} 起未闭环事件
          </div>
          <Table
            dataSource={alerts}
            columns={columns}
            rowKey="eventId"
            size="small"
            pagination={false}
            scroll={{ y: 220 }}
          />
        </>
      )}
    </Card>
  );
}
