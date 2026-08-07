/** Workflow V1 动作记录卡片 */
import React from 'react';
import { Card, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';

interface Props {
  actionId: string;
  actionType: string;
  status: string;
  idempotencyKey: string;
  error?: string;
  result?: Record<string, unknown>;
  createdAt?: string;
  completedAt?: string;
}

export const WorkflowActionRecordCard: React.FC<Props> = ({
  actionId, actionType, status, idempotencyKey, error, result, createdAt,
}) => {
  const isSuccess = status === 'succeeded';
  const isFailed = status === 'failed';

  return (
    <Card
      size="small"
      style={{ marginBottom: 8 }}
      title={
        <span>
          {isSuccess ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> :
           isFailed ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> :
           null} {actionType}
        </span>
      }
      extra={<Tag color={isSuccess ? 'success' : isFailed ? 'error' : 'default'}>{status}</Tag>}
    >
      <Typography.Paragraph style={{ fontSize: 12, marginBottom: 4 }}>
        <Typography.Text type="secondary">幂等键: </Typography.Text>
        <Typography.Text code style={{ fontSize: 11 }}>{idempotencyKey}</Typography.Text>
      </Typography.Paragraph>
      {error && <Typography.Text type="danger" style={{ fontSize: 12 }}>错误: {error}</Typography.Text>}
      {result && Object.keys(result).length > 0 && (
        <Typography.Paragraph style={{ fontSize: 12, marginTop: 4 }}>
          <Typography.Text type="secondary">结果: </Typography.Text>
          <Typography.Text code style={{ fontSize: 11 }}>{JSON.stringify(result)}</Typography.Text>
        </Typography.Paragraph>
      )}
    </Card>
  );
};
