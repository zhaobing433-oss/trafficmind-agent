/**
 * 高风险路口 TopN 面板
 */
import { useState, useEffect } from 'react';
import { Card, Table, Tag, Button, Spin, Empty } from 'antd';
import { EnvironmentOutlined, ReloadOutlined } from '@ant-design/icons';
import { getHighRiskRoads } from '../api';
import type { HighRiskRoad } from '../types';

export default function HighRiskRoadsPanel() {
  const [loading, setLoading] = useState(false);
  const [roads, setRoads] = useState<HighRiskRoad[]>([]);

  const fetchRoads = async () => {
    setLoading(true);
    try {
      const result = await getHighRiskRoads(10, 30, '低风险');
      setRoads(result.topRoads);
    } catch (e) {
      // 静默
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRoads();
  }, []);

  const columns = [
    {
      title: '路口', dataIndex: 'roadName', key: 'roadName', ellipsis: true,
      render: (v: string) => <span><EnvironmentOutlined style={{ color: '#1677ff' }} /> {v}</span>,
    },
    { title: '事件总数', dataIndex: 'totalEvents', key: 'total', width: 70 },
    {
      title: '高风险', key: 'high', width: 60,
      render: (_: unknown, r: HighRiskRoad) => (
        <Tag color="red">{r.highRiskCount + r.majorRiskCount}</Tag>
      ),
    },
    { title: '未闭环', dataIndex: 'unclosedCount', key: 'unclosed', width: 60 },
    {
      title: '平均分', dataIndex: 'avgRiskScore', key: 'avg', width: 60,
      render: (v: number) => <span style={{ fontWeight: 'bold' }}>{v}</span>,
    },
    { title: '最常见', dataIndex: 'mostCommonEventType', key: 'type', width: 70 },
    { title: '建议', dataIndex: 'suggestedAction', key: 'action', ellipsis: true, width: 200 },
  ];

  return (
    <Card
      title={<span><EnvironmentOutlined style={{ color: '#1677ff' }} /> 高风险路口 Top N</span>}
      size="small"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchRoads} loading={loading} />}
      style={{ height: '100%', background: 'rgba(16,20,52,0.85)', borderColor: 'rgba(255,255,255,0.08)' }}
    >
      {loading && !roads.length ? (
        <Spin />
      ) : roads.length === 0 ? (
        <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table
          dataSource={roads}
          columns={columns}
          rowKey="roadName"
          size="small"
          pagination={false}
          scroll={{ y: 220 }}
        />
      )}
    </Card>
  );
}
