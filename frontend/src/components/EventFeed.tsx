import { List, Typography } from 'antd';
import { AlertOutlined } from '@ant-design/icons';
import type { EventRecord } from '../types';
import { riskLevelColor, formatDateTime } from '../utils/format';

interface Props {
  events: EventRecord[];
}

export default function EventFeed({ events }: Props) {
  // 只展示最近 10 条高风险及以上的事件
  const highRiskEvents = events
    .filter((e) => e.riskLevel === '高风险' || e.riskLevel === '重大风险')
    .slice(0, 10);

  return (
    <div style={{
      background: 'rgba(16,20,52,0.7)',
      backdropFilter: 'blur(10px)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: 8,
      padding: 16,
      borderTop: '2px solid #ff4d4f',
      display: 'flex',
      flexDirection: 'column',
      maxHeight: 500,
    }}>
      <h3 style={{
        margin: '0 0 12px',
        fontSize: 14,
        color: 'rgba(255,255,255,0.55)',
        letterSpacing: 1,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        <AlertOutlined style={{ color: '#ff4d4f' }} />
        高风险事件推送
      </h3>

      {highRiskEvents.length === 0 ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(255,255,255,0.3)' }}>
          暂无高风险事件
        </div>
      ) : (
        <List
          dataSource={highRiskEvents}
          renderItem={(item) => (
            <List.Item style={{ padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <div style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{
                    fontWeight: 600,
                    color: riskLevelColor(item.riskLevel),
                    fontSize: 13,
                  }}>
                    [{item.riskLevel}] {item.eventTypeCn}
                  </span>
                  <Typography.Text style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>
                    {formatDateTime(item.createdAt)}
                  </Typography.Text>
                </div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)' }}>
                  📍 {item.roadName}
                </div>
              </div>
            </List.Item>
          )}
        />
      )}
    </div>
  );
}
