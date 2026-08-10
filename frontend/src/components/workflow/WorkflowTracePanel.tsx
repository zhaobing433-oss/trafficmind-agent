/** Workflow V1 Trace 面板 */
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Tabs, Spin, Empty, Typography, Tag, Descriptions, Alert } from 'antd';
import {
  getRunTrace, getRun, type WorkflowTrace, type WorkflowRunDetail,
} from '../../api/workflowApi';
import { RUN_STATUS_COLORS } from '../../types/workflow';
import type { WorkflowRunStatus, NodeType, NodeStatus, ApprovalDecision } from '../../types/workflow';
import { WorkflowRunTimeline } from './WorkflowRunTimeline';
import { WorkflowNodeCard } from './WorkflowNodeCard';
import { WorkflowApprovalCard } from './WorkflowApprovalCard';
import { WorkflowActionRecordCard } from './WorkflowActionRecordCard';
import { WorkflowErrorBoundary } from './WorkflowErrorBoundary';
import { processApproval, resumeRun } from '../../api/workflowApi';

interface Props {
  runId: string;
  visible?: boolean;
  onRefresh?: () => void;
}

export const WorkflowTracePanel: React.FC<Props> = ({ runId, visible = true, onRefresh }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<WorkflowTrace | null>(null);
  const [detail, setDetail] = useState<WorkflowRunDetail | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      const [t, d] = await Promise.all([
        getRunTrace(runId),
        getRun(runId),
      ]);
      setTrace(t);
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load trace');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    if (visible && runId) { load(); }
  }, [runId, visible, load]);

  const handleApprove = async (approvalId: string, comment: string) => {
    await processApproval(runId, approvalId, { action: 'approve', comment });
    // Resume execution after approval
    resumeRun(runId, { onEvent: () => {}, onDone: () => { load(); onRefresh?.(); } });
  };

  const handleReject = async (approvalId: string, comment: string) => {
    await processApproval(runId, approvalId, { action: 'reject', comment });
    await load();
    onRefresh?.();
  };

  const handleEditAndApprove = async (approvalId: string, editedActions: Array<Record<string, unknown>>, comment: string) => {
    await processApproval(runId, approvalId, { action: 'edit_and_approve', editedActions, comment });
    await load();
    onRefresh?.();
  };

  if (loading && !trace) return <Spin tip="加载 Trace..." />;
  if (error) return <Alert type="error" message={error} />;
  if (!trace && !detail) return <Empty description="无 Trace 数据" />;

  const status = (trace?.status || 'pending') as WorkflowRunStatus;

  const timelineEntries = (trace?.timeline || []).map((e: Record<string, unknown>) => ({
    eventType: e.eventType as string || '',
    nodeId: e.nodeId as string || '',
    nodeType: e.nodeType as NodeType | undefined,
    status: e.status as NodeStatus | undefined,
    attempt: e.attempt as number | undefined,
    error: e.error as string | undefined,
    payload: e.payload as Record<string, unknown> | undefined,
    createdAt: e.createdAt as string || '',
    sequence: (e.sequence as number) || 0,
  }));

  const nodeRunEntries = (trace?.nodeRuns || []).map((nr: Record<string, unknown>) => ({
    nodeId: nr.nodeId as string,
    nodeType: nr.nodeType as NodeType,
    status: nr.status as NodeStatus,
    attempt: (nr.attempt as number) || 1,
    error: (nr.error as string) || '',
    startedAt: (nr.startedAt as string) || '',
    completedAt: (nr.completedAt as string) || '',
  }));

  const actionRecords = (trace?.actionRecords || [])
    .map((a: Record<string, unknown>) => ({
      actionId: a.actionId as string, runId: a.runId as string,
      nodeId: a.nodeId as string, actionType: a.actionType as string,
      idempotencyKey: a.idempotencyKey as string,
      status: a.status as string || 'unknown',
      error: a.error as string || '', result: a.result as Record<string, unknown> || {},
      createdAt: a.createdAt as string || '', completedAt: a.completedAt as string || '',
    }));

  const state = detail?.state || {};
  const pendingApproval = (state as Record<string, unknown>).pendingApproval as Record<string, unknown> | null;

  return (
    <WorkflowErrorBoundary runId={runId}>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="Run ID">{runId}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={RUN_STATUS_COLORS[status] || 'default'}>{status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="版本">{trace?.version || '-'}</Descriptions.Item>
          <Descriptions.Item label="Definition">{trace?.definitionId || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Tabs
        defaultActiveKey="timeline"
        items={[
          {
            key: 'timeline',
            label: `时间线 (${timelineEntries.length})`,
            children: <WorkflowRunTimeline timeline={timelineEntries} nodeRuns={nodeRunEntries} />,
          },
          {
            key: 'nodes',
            label: `节点 (${nodeRunEntries.length})`,
            children: (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {nodeRunEntries.map((nr, i) => (
                  <WorkflowNodeCard
                    key={i}
                    nodeId={nr.nodeId}
                    nodeType={nr.nodeType}
                    label={nr.nodeId}
                    status={nr.status}
                    attempt={nr.attempt}
                    error={nr.error}
                    startedAt={nr.startedAt}
                    completedAt={nr.completedAt}
                  />
                ))}
              </div>
            ),
          },
          {
            key: 'approval',
            label: '审批',
            children: pendingApproval ? (
              <WorkflowApprovalCard
                approvalId={(pendingApproval.approvalId as string) || ''}
                runId={runId}
                nodeId={(pendingApproval.nodeId as string) || ''}
                proposedActions={(pendingApproval.proposedActions as Array<Record<string, unknown>>) || []}
                decision={(pendingApproval.decision as ApprovalDecision) || 'pending'}
                reviewer={(pendingApproval.reviewer as string) || ''}
                comment={(pendingApproval.comment as string) || ''}
                createdAt={(pendingApproval.createdAt as string) || ''}
                decidedAt={(pendingApproval.decidedAt as string) || ''}
                onApprove={(c) => handleApprove((pendingApproval.approvalId as string) || '', c)}
                onReject={(c) => handleReject((pendingApproval.approvalId as string) || '', c)}
                onEditAndApprove={(a, c) => handleEditAndApprove((pendingApproval.approvalId as string) || '', a, c)}
              />
            ) : (
              <Empty description="无待审批项" />
            ),
          },
          {
            key: 'actions',
            label: `动作 (${actionRecords.length})`,
            children: actionRecords.length > 0 ? (
              actionRecords.map((ar, i) => (
                <WorkflowActionRecordCard key={i} {...ar} />
              ))
            ) : (
              <Empty description="无外部动作记录" />
            ),
          },
        ]}
      />
    </WorkflowErrorBoundary>
  );
};
