import { Modal, Descriptions, Tag, Spin, Typography, Divider } from 'antd';
import type { EventRecord, AnalyzeResult } from '../types';
import { riskLevelColor, formatDateTime } from '../utils/format';

interface Props {
  open: boolean;
  event: EventRecord | null;
  detailData: AnalyzeResult | null;
  onClose: () => void;
}

const sectionStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  borderRadius: 6,
  padding: 16,
  marginBottom: 12,
};

export default function EventDetailModal({ open, event, detailData, onClose }: Props) {
  if (!event) return null;

  return (
    <Modal
      title={
        <span style={{ fontSize: 16 }}>
          事件详情 — {event.eventId}
        </span>
      }
      open={open}
      onCancel={onClose}
      width={900}
      footer={null}
      styles={{ body: { maxHeight: '70vh', overflow: 'auto', padding: '16px 24px' } }}
    >
      {!detailData ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="加载详情中…" />
        </div>
      ) : (
        <>
          {/* — 事件概况 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: '#4facfe' }}>
              一、事件概况
            </Typography.Title>
            <Descriptions size="small" column={3} labelStyle={{ color: 'rgba(255,255,255,0.45)' }}>
              <Descriptions.Item label="事件类型">
                <Tag>{detailData.standardEvent.eventTypeCn}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="事发路段">{detailData.standardEvent.roadName}</Descriptions.Item>
              <Descriptions.Item label="方向">{detailData.standardEvent.direction || '-'}</Descriptions.Item>
              <Descriptions.Item label="车道">{detailData.standardEvent.lane || '-'}</Descriptions.Item>
              <Descriptions.Item label="平均车速">{detailData.standardEvent.avgSpeed} km/h</Descriptions.Item>
              <Descriptions.Item label="排队长度">{detailData.standardEvent.queueLength} 米</Descriptions.Item>
              <Descriptions.Item label="持续时间">{Math.floor(detailData.standardEvent.duration / 60)} 分钟</Descriptions.Item>
              <Descriptions.Item label="涉及车辆">{detailData.standardEvent.vehicleCount} 辆</Descriptions.Item>
              <Descriptions.Item label="置信度">{detailData.standardEvent.confidence}</Descriptions.Item>
            </Descriptions>
          </div>

          {/* 二、风险等级 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: '#faad14' }}>
              二、风险等级
            </Typography.Title>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <span style={{ fontSize: 36, fontWeight: 700, color: riskLevelColor(detailData.riskLevel) }}>
                {detailData.riskScore}
              </span>
              <Tag color={riskLevelColor(detailData.riskLevel)} style={{ fontSize: 16, padding: '2px 12px' }}>
                {detailData.riskLevel}
              </Tag>
              <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 12 }}>
                {formatDateTime(detailData.analyzedAt)}
              </span>
            </div>
          </div>

          {/* 三、研判依据 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: '#ff7a45' }}>
              三、研判依据
            </Typography.Title>
            {detailData.riskReasons.map((r, i) => (
              <div key={i} style={{ fontSize: 13, color: 'rgba(255,255,255,0.6)', marginBottom: 4 }}>
                {i + 1}. {r}
              </div>
            ))}
          </div>

          {/* 四、处置建议 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: '#52c41a' }}>
              四、处置建议
            </Typography.Title>
            {detailData.suggestions.map((s, i) => (
              <div key={i} style={{ fontSize: 13, color: 'rgba(255,255,255,0.6)', marginBottom: 4 }}>
                {i + 1}. {s}
              </div>
            ))}
          </div>

          {/* 五、调度话术 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: '#1677ff' }}>
              五、调度话术
            </Typography.Title>
            <Typography.Paragraph style={{
              fontSize: 13,
              color: 'rgba(255,255,255,0.6)',
              whiteSpace: 'pre-wrap',
              margin: 0,
            }}>
              {detailData.dispatchMessage}
            </Typography.Paragraph>
          </div>

          {/* 六、公众提示 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: '#eb2f96' }}>
              六、公众提示
            </Typography.Title>
            <div style={{
              fontSize: 14,
              color: '#ffccc7',
              background: 'rgba(255,77,79,0.1)',
              padding: '8px 12px',
              borderRadius: 4,
              borderLeft: '3px solid #ff4d4f',
            }}>
              {detailData.publicMessage}
            </div>
          </div>

          <Divider style={{ borderColor: 'rgba(255,255,255,0.06)' }} />

          {/* 完整报告 */}
          <div style={sectionStyle}>
            <Typography.Title level={5} style={{ margin: '0 0 8px', color: 'rgba(255,255,255,0.55)' }}>
              完整研判报告
            </Typography.Title>
            <pre style={{
              fontSize: 12,
              color: 'rgba(255,255,255,0.55)',
              whiteSpace: 'pre-wrap',
              fontFamily: 'inherit',
              lineHeight: 1.6,
              margin: 0,
            }}>
              {detailData.report}
            </pre>
          </div>
        </>
      )}
    </Modal>
  );
}
