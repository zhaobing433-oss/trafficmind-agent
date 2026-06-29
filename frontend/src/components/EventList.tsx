import { Table, Select } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { EventRecord } from '../types';
import StatusBadge from './StatusBadge';
import { riskLevelColor, formatDateTime } from '../utils/format';
import { updateEventStatus } from '../api';

interface Props {
  events: EventRecord[];
  onRowClick: (event: EventRecord) => void;
  onStatusChange: () => void;
}

const STATUS_OPTIONS = [
  { value: '待研判', label: '待研判' },
  { value: '待派单', label: '待派单' },
  { value: '处置中', label: '处置中' },
  { value: '已处置', label: '已处置' },
  { value: '待复盘', label: '待复盘' },
  { value: '已归档', label: '已归档' },
];

export default function EventList({ events, onRowClick, onStatusChange }: Props) {
  const columns: ColumnsType<EventRecord> = [
    {
      title: '事件编号',
      dataIndex: 'eventId',
      key: 'eventId',
      width: 160,
      render: (id: string) => (
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#8cb4ff' }}>{id}</span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'eventTypeCn',
      key: 'eventTypeCn',
      width: 100,
    },
    {
      title: '路段',
      dataIndex: 'roadName',
      key: 'roadName',
      ellipsis: true,
    },
    {
      title: '风险分',
      dataIndex: 'riskScore',
      key: 'riskScore',
      width: 80,
      sorter: (a, b) => a.riskScore - b.riskScore,
      render: (score: number, record: EventRecord) => (
        <span style={{ color: riskLevelColor(record.riskLevel), fontWeight: 600 }}>{score}</span>
      ),
    },
    {
      title: '风险等级',
      dataIndex: 'riskLevel',
      key: 'riskLevel',
      width: 90,
      render: (level: string) => (
        <span style={{ color: riskLevelColor(level), fontWeight: 500 }}>{level}</span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (status: string, record: EventRecord) => (
        <Select
          value={status}
          size="small"
          style={{ width: 110 }}
          options={STATUS_OPTIONS}
          onClick={(e) => e.stopPropagation()}
          onChange={async (newStatus) => {
            try {
              await updateEventStatus(record.eventId, newStatus);
              onStatusChange();
            } catch {
              // silently fail
            }
          }}
        />
      ),
    },
    {
      title: '时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 160,
      render: (t: string) => formatDateTime(t),
    },
  ];

  return (
    <div style={{
      background: 'rgba(16,20,52,0.7)',
      backdropFilter: 'blur(10px)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: 8,
      padding: 16,
      borderTop: '2px solid #1677ff',
    }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 14, color: 'rgba(255,255,255,0.55)', letterSpacing: 1 }}>
        事件列表
      </h3>
      <Table<EventRecord>
        dataSource={events}
        columns={columns}
        rowKey="eventId"
        size="small"
        pagination={{ pageSize: 10, showSizeChanger: false }}
        onRow={(record) => ({
          onClick: () => onRowClick(record),
          style: { cursor: 'pointer' },
        })}
        locale={{ emptyText: '暂无事件记录' }}
      />
    </div>
  );
}
