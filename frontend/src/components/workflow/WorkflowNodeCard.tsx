/** Workflow V1 节点卡片 */
import React from 'react';
import { Tag, Typography, Tooltip } from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  SyncOutlined, StopOutlined, QuestionCircleOutlined,
} from '@ant-design/icons';
import type { NodeStatus, NodeType } from '../../types/workflow';
import { NODE_TYPE_LABELS, NODE_STATUS_COLORS } from '../../types/workflow';

interface Props {
  nodeId: string;
  nodeType: NodeType;
  label: string;
  status: NodeStatus;
  attempt?: number;
  maxAttempts?: number;
  error?: string;
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  onClick?: () => void;
}

const StatusIcon: React.FC<{ status: NodeStatus }> = ({ status }) => {
  switch (status) {
    case 'succeeded': return <CheckCircleOutlined style={{ color: NODE_STATUS_COLORS.succeeded }} />;
    case 'failed': return <CloseCircleOutlined style={{ color: NODE_STATUS_COLORS.failed }} />;
    case 'running': return <SyncOutlined spin style={{ color: NODE_STATUS_COLORS.running }} />;
    case 'pending': return <ClockCircleOutlined style={{ color: NODE_STATUS_COLORS.pending }} />;
    case 'retrying': return <SyncOutlined spin style={{ color: NODE_STATUS_COLORS.retrying }} />;
    case 'timed_out': return <StopOutlined style={{ color: NODE_STATUS_COLORS.timed_out }} />;
    case 'awaiting_approval': return <QuestionCircleOutlined style={{ color: NODE_STATUS_COLORS.awaiting_approval }} />;
    default: return <ClockCircleOutlined />;
  }
};

export const WorkflowNodeCard: React.FC<Props> = ({
  nodeId, nodeType, label, status, attempt, maxAttempts, error, startedAt, completedAt, durationMs, onClick,
}) => {
  const typeLabel = NODE_TYPE_LABELS[nodeType] || nodeType;
  const retryInfo = attempt && maxAttempts && maxAttempts > 1 ? ` (${attempt}/${maxAttempts})` : '';

  const card = (
    <div
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px', borderRadius: 8,
        border: `1.5px solid ${NODE_STATUS_COLORS[status] || '#d9d9d9'}`,
        background: status === 'running' ? '#e6f7ff' : '#fff',
        cursor: onClick ? 'pointer' : 'default',
        minWidth: 220,
      }}
    >
      <StatusIcon status={status} />
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{label || nodeId}</div>
        <div style={{ fontSize: 12, color: '#8c8c8c' }}>
          <Tag color="default" style={{ fontSize: 11 }}>{typeLabel}</Tag>
          <Tag color={status === 'succeeded' ? 'success' : status === 'failed' ? 'error' : 'default'}>
            {status}{retryInfo}
          </Tag>
        </div>
        {error && (
          <Tooltip title={error}>
            <Typography.Text type="danger" style={{ fontSize: 11 }} ellipsis>
              {error.slice(0, 60)}
            </Typography.Text>
          </Tooltip>
        )}
        {durationMs != null && durationMs > 0 && (
          <div style={{ fontSize: 11, color: '#bfbfbf' }}>{(durationMs / 1000).toFixed(1)}s</div>
        )}
      </div>
    </div>
  );

  return card;
};
