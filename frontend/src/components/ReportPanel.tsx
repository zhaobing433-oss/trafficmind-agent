/**
 * 日报 / 周报生成面板
 */
import { useState } from 'react';
import { Card, Button, Spin, message, Tabs } from 'antd';
import { FileTextOutlined, BarChartOutlined } from '@ant-design/icons';
import { getDailyReport, getWeeklyReport } from '../api';
import type { DailyReportResponse, WeeklyReportResponse } from '../types';

export default function ReportPanel() {
  const [loading, setLoading] = useState(false);
  const [reportText, setReportText] = useState<string>('');
  const [reportTitle, setReportTitle] = useState<string>('');

  const handleDaily = async () => {
    setLoading(true);
    try {
      const r: DailyReportResponse = await getDailyReport();
      setReportTitle(`日报 — ${r.date}`);
      setReportText(r.reportText);
      message.success(`日报生成完成：${r.totalEvents} 起事件`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '日报生成失败');
    } finally {
      setLoading(false);
    }
  };

  const handleWeekly = async () => {
    setLoading(true);
    try {
      const r: WeeklyReportResponse = await getWeeklyReport();
      setReportTitle(`周报 — ${r.startDate} ~ ${r.endDate}`);
      setReportText(r.reportText);
      message.success(`周报生成完成：${r.totalEvents} 起事件`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '周报生成失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card
      title={<span><FileTextOutlined style={{ color: '#1677ff' }} /> 报告生成</span>}
      size="small"
      extra={
        <span>
          <Button size="small" icon={<BarChartOutlined />} onClick={handleDaily} style={{ marginRight: 8 }}>
            日报
          </Button>
          <Button size="small" icon={<BarChartOutlined />} onClick={handleWeekly}>
            周报
          </Button>
        </span>
      }
      style={{ height: '100%', background: 'rgba(16,20,52,0.85)', borderColor: 'rgba(255,255,255,0.08)' }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="正在生成报告..." />
        </div>
      ) : reportText ? (
        <div>
          <div style={{ marginBottom: 8, fontWeight: 'bold', color: '#1677ff' }}>
            {reportTitle}
          </div>
          <pre style={{
            whiteSpace: 'pre-wrap',
            fontSize: 12,
            maxHeight: 400,
            overflow: 'auto',
            color: '#d0d0d0',
            background: 'rgba(0,0,0,0.3)',
            padding: 12,
            borderRadius: 4,
          }}>
            {reportText}
          </pre>
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: 40, color: '#888' }}>
          点击「日报」或「周报」生成交通事件管理报告
        </div>
      )}
    </Card>
  );
}
