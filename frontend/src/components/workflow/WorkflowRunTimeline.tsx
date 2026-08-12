/** Workflow V1 运行时间线 */
import React from 'react';
import { Timeline, Typography, Tag, Empty } from 'antd';
import { NODE_TYPE_LABELS, NODE_STATUS_COLORS } from '../../types/workflow';
import type { NodeStatus, NodeType } from '../../types/workflow';

interface TimelineEntry {
  eventType: string;
  nodeId: string;
  nodeType?: NodeType;
  status?: NodeStatus;
  attempt?: number;
  error?: string;
  payload?: Record<string, unknown>;
  createdAt: string;
  sequence: number;
}

interface Props {
  timeline: TimelineEntry[];
  nodeRuns: Array<{
    nodeId: string;
    nodeType: NodeType;
    status: NodeStatus;
    attempt: number;
    error: string;
    startedAt: string;
    completedAt: string;
  }>;
}

export const WorkflowRunTimeline: React.FC<Props> = ({ timeline, nodeRuns }) => {
  if (!timeline || timeline.length === 0) {
    return <Empty description="暂无时间线数据" />;
  }

  const sorted = [...timeline].sort((a, b) => a.sequence - b.sequence);

  const items = sorted.map((entry) => {
    const typeLabel = entry.nodeType ? (NODE_TYPE_LABELS[entry.nodeType] || entry.nodeType) : '';
    const color = entry.status ? NODE_STATUS_COLORS[entry.status] : '#1890ff';

    let description = '';
    if (entry.nodeId) description += `节点: ${entry.nodeId}`;
    if (typeLabel) description += ` [${typeLabel}]`;
    if (entry.attempt && entry.attempt > 1) description += ` (第${entry.attempt}次)`;
    if (entry.error) description += ` — ${entry.error.slice(0, 80)}`;

    return {
      color,
      children: (
        <div>
          <Typography.Text strong>{entry.eventType}</Typography.Text>
          {description && (
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {description}
              </Typography.Text>
            </div>
          )}
          {entry.createdAt && (
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {entry.createdAt}
            </Typography.Text>
          )}
        </div>
      ),
    };
  });

  return (
    <div>
      <Typography.Title level={5} style={{ marginTop: 0 }}>
        节点执行记录
      </Typography.Title>
      <div style={{ marginBottom: 16 }}>
        {nodeRuns.map((nr, i) => (
          <Tag
            key={i}
            color={NODE_STATUS_COLORS[nr.status] || 'default'}
            style={{ marginBottom: 4 }}
          >
            {nr.nodeId}: {nr.status}
            {nr.attempt > 1 ? ` (${nr.attempt})` : ''}
          </Tag>
        ))}
      </div>
      <Typography.Title level={5}>时间线</Typography.Title>
      <Timeline items={items} />
    </div>
  );
};
