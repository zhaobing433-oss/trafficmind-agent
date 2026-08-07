/** Workflow V1 审批卡片 */
import React, { useState } from 'react';
import { Card, Button, Input, Space, Tag, Typography, List, message, Popconfirm } from 'antd';
import type { ApprovalDecision } from '../../types/workflow';

interface Props {
  approvalId: string;
  runId: string;
  nodeId: string;
  proposedActions: Array<Record<string, unknown>>;
  decision: ApprovalDecision;
  reviewer: string;
  comment: string;
  createdAt: string;
  decidedAt: string;
  onApprove: (comment: string) => Promise<void>;
  onReject: (comment: string) => Promise<void>;
  onEditAndApprove: (editedActions: Array<Record<string, unknown>>, comment: string) => Promise<void>;
  disabled?: boolean;
}

export const WorkflowApprovalCard: React.FC<Props> = ({
  approvalId, runId, nodeId, proposedActions, decision,
  reviewer, comment, createdAt, decidedAt,
  onApprove, onReject, onEditAndApprove, disabled,
}) => {
  const [approveComment, setApproveComment] = useState('');
  const [rejectComment, setRejectComment] = useState('');
  const [editing, setEditing] = useState(false);
  const [editedActions, setEditedActions] = useState(proposedActions);
  const [loading, setLoading] = useState(false);

  const isPending = decision === 'pending';

  const handleApprove = async () => {
    setLoading(true);
    try {
      await onApprove(approveComment);
      message.success('已批准');
    } catch (e: unknown) {
      message.error(`批准失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    setLoading(true);
    try {
      await onReject(rejectComment);
      message.success('已驳回');
    } catch (e: unknown) {
      message.error(`驳回失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setLoading(false);
    }
  };

  const handleEditAndApprove = async () => {
    setLoading(true);
    try {
      await onEditAndApprove(editedActions, approveComment);
      message.success('已编辑并批准');
    } catch (e: unknown) {
      message.error(`操作失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setLoading(false);
    }
  };

  const decisionColor: Record<ApprovalDecision, string> = {
    pending: 'processing', approved: 'success', rejected: 'error', edited: 'warning',
  };

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>人工审批</span>
          <Tag color={decisionColor[decision]}>{decision}</Tag>
          {reviewer && <Typography.Text type="secondary">审批人: {reviewer}</Typography.Text>}
        </Space>
      }
      style={{ marginBottom: 12, borderLeft: '3px solid #722ed1' }}
    >
      <div style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          ID: {approvalId} | 节点: {nodeId}
        </Typography.Text>
      </div>

      <Typography.Text strong>提议动作:</Typography.Text>
      <List
        size="small"
        dataSource={proposedActions}
        renderItem={(action, i) => (
          <List.Item key={i} style={{ padding: '4px 0' }}>
            <Typography.Text code>{JSON.stringify(action)}</Typography.Text>
          </List.Item>
        )}
      />

      {comment && (
        <div style={{ marginTop: 8 }}>
          <Typography.Text type="secondary">意见: {comment}</Typography.Text>
        </div>
      )}

      {decision !== 'pending' && decidedAt && (
        <div style={{ marginTop: 4 }}>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            决策时间: {decidedAt}
          </Typography.Text>
        </div>
      )}

      {isPending && !disabled && (
        <div style={{ marginTop: 12 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Input.TextArea
              rows={2}
              placeholder="审批意见（可选）"
              value={approveComment}
              onChange={e => setApproveComment(e.target.value)}
            />
            <Space>
              <Button type="primary" loading={loading} onClick={handleApprove}>
                批准 (Approve)
              </Button>
              {editing ? (
                <>
                  <Input.TextArea
                    rows={3}
                    value={JSON.stringify(editedActions, null, 2)}
                    onChange={e => {
                      try { setEditedActions(JSON.parse(e.target.value)); } catch { /* invalid JSON */ }
                    }}
                  />
                  <Button type="primary" onClick={handleEditAndApprove} loading={loading}>
                    保存编辑并批准
                  </Button>
                  <Button onClick={() => setEditing(false)}>取消编辑</Button>
                </>
              ) : (
                <Button onClick={() => setEditing(true)}>编辑并批准 (Edit & Approve)</Button>
              )}
              <Popconfirm
                title="确定驳回?"
                description={
                  <Input.TextArea
                    rows={2}
                    placeholder="驳回原因"
                    value={rejectComment}
                    onChange={e => setRejectComment(e.target.value)}
                  />
                }
                onConfirm={handleReject}
                okText="驳回"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button danger loading={loading}>驳回 (Reject)</Button>
              </Popconfirm>
            </Space>
          </Space>
        </div>
      )}
    </Card>
  );
};
