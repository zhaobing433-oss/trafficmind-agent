/**
 * 历史相似案例面板
 */
import { useState } from 'react';
import { Card, Table, Tag, Button, Spin, Empty, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { getSimilarCases } from '../api';
import type { SimilarCase } from '../types';

interface Props {
  currentEventId?: string;
}

const RISK_COLORS: Record<string, string> = {
  '低风险': 'green',
  '中风险': 'orange',
  '高风险': 'red',
  '重大风险': 'magenta',
};

export default function SimilarCasesPanel({ currentEventId }: Props) {
  const [loading, setLoading] = useState(false);
  const [cases, setCases] = useState<SimilarCase[]>([]);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!currentEventId) {
      message.warning('请先分析一个事件');
      return;
    }
    setLoading(true);
    setSearched(true);
    try {
      const result = await getSimilarCases(currentEventId, 5, 0.3);
      setCases(result.similarCases);
      if (result.similarCases.length === 0) {
        message.info('未找到相似案例');
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '查询失败');
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    { title: '事件ID', dataIndex: 'eventId', key: 'eventId', width: 140 },
    { title: '类型', dataIndex: 'eventType', key: 'eventType', width: 80 },
    { title: '路段', dataIndex: 'roadName', key: 'roadName', ellipsis: true },
    {
      title: '风险', dataIndex: 'riskLevel', key: 'riskLevel', width: 80,
      render: (v: string) => <Tag color={RISK_COLORS[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '相似度', dataIndex: 'similarityScore', key: 'similarityScore', width: 80,
      render: (v: number) => (
        <span style={{ color: v >= 0.7 ? '#52c41a' : '#faad14', fontWeight: 'bold' }}>
          {(v * 100).toFixed(0)}%
        </span>
      ),
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80 },
  ];

  return (
    <Card
      title="历史相似案例"
      size="small"
      extra={
        <Button size="small" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
          检索
        </Button>
      }
      style={{ height: '100%', background: 'rgba(16,20,52,0.85)', borderColor: 'rgba(255,255,255,0.08)' }}
    >
      {!searched ? (
        <Empty description="点击「检索」查找相似案例" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : loading ? (
        <Spin tip="检索中..." />
      ) : (
        <Table
          dataSource={cases}
          columns={columns}
          rowKey="eventId"
          size="small"
          pagination={false}
          scroll={{ y: 200 }}
          onRow={(record) => ({
            onClick: () => {
              message.info(`相似原因：${record.similarityReasons?.join('；')}`);
            },
            style: { cursor: 'pointer' },
          })}
        />
      )}
    </Card>
  );
}
