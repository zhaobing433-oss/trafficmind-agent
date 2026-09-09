/**
 * WorkflowRunCard — Workflow Center V2 Round 2
 *
 * 显示单个 Run 摘要卡片。
 * 点击进入 Run 详情（复用现有 WorkflowTracePanel）。
 */
import React from 'react';
import type { RunSummary, WorkflowRunStatus } from '../../types/workflow';
import { RUN_STATUS_LABELS, APPROVAL_STATUS_LABELS } from '../../types/workflow';
import { formatDateTime } from '../../utils/format';

interface Props {
  run: RunSummary;
  onClick: (runId: string) => void;
}

/** 状态 Badge 颜色（沿用项目现有 RUN_STATUS_COLORS） */
const STATUS_COLORS: Record<WorkflowRunStatus, { bg: string; text: string; border: string }> = {
  pending:       { bg: '#F9FAFB', text: '#6B7280', border: '#E5E7EB' },
  running:       { bg: '#EFF6FF', text: '#1D4ED8', border: '#BFDBFE' },
  paused:        { bg: '#FFFBEB', text: '#92400E', border: '#FDE68A' },
  awaiting_approval: { bg: '#F5F3FF', text: '#5B21B6', border: '#DDD6FE' },
  completed:     { bg: '#F0FDF4', text: '#166534', border: '#BBF7D0' },
  failed:        { bg: '#FEF2F2', text: '#991B1B', border: '#FECACA' },
  rejected:      { bg: '#FFF7ED', text: '#9A3412', border: '#FED7AA' },
  cancelled:     { bg: '#F9FAFB', text: '#6B7280', border: '#E5E7EB' },
};

export const WorkflowRunCard: React.FC<Props> = ({ run, onClick }) => {
  const colors = STATUS_COLORS[run.status] || STATUS_COLORS.pending;
  const statusLabel = RUN_STATUS_LABELS[run.status] || run.status;
  const es = run.eventSummary;

  // ── 业务标题 ──
  const parts: string[] = [];
  if (es?.roadName) parts.push(es.roadName);
  if (es?.eventTypeCn) parts.push(es.eventTypeCn);
  const primaryTitle = parts.length > 0 ? parts.join(' · ') : (run.definitionName || '工作流运行');

  // ── 节点进度 ──
  let progressText = '';
  const p = run.progress;
  if (p.totalNodes !== null && p.totalNodes > 0) {
    const done = run.isTerminal ? p.succeededNodes : p.executedNodes;
    progressText = `节点 ${done}/${p.totalNodes}`;
  } else if (p.executedNodes > 0) {
    progressText = `已执行 ${p.executedNodes} 个节点`;
  }

  // ── 审批 ──
  // 当 run status 本身就是 awaiting_approval 时，避免与 badge 重复
  let approvalLabel: string;
  if (run.status === 'awaiting_approval' && run.approvalSummary.status === 'awaiting_approval') {
    approvalLabel = '等待人工审批';
  } else {
    approvalLabel = APPROVAL_STATUS_LABELS[run.approvalSummary.status] || run.approvalSummary.status;
  }

  // ── 动作 ──
  let actionText = '';
  const a = run.actionSummary;
  if (a.total === 0) {
    actionText = '无动作';
  } else {
    const parts2 = [`动作 ${a.succeeded}/${a.total}`];
    if (a.failed > 0) parts2.push(`失败 ${a.failed}`);
    actionText = parts2.join(' · ');
  }

  // ── 失败节点 ──
  const failedNodeInfo = p.failedNodes > 0 ? `失败节点 ${p.failedNodes}` : '';

  // ── 时间 ──
  const timeLabel = run.updatedAt
    ? `更新于 ${formatDateTime(run.updatedAt)}`
    : '';

  return (
    <div
      onClick={() => onClick(run.runId)}
      style={{
        padding: '16px 20px',
        borderRadius: 10,
        border: '1.5px solid #E5E7EB',
        background: '#FFFFFF',
        cursor: 'pointer',
        transition: 'all 0.15s',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = '#0F766E'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = '#E5E7EB'; }}
    >
      {/* Row 1: Status Badge */}
      <div style={{ marginBottom: 6 }}>
        <span style={{
          display: 'inline-block',
          padding: '2px 10px',
          borderRadius: 12,
          fontSize: 11,
          fontWeight: 600,
          background: colors.bg,
          color: colors.text,
          border: `1px solid ${colors.border}`,
        }}>
          {statusLabel}
        </span>
      </div>

      {/* Row 2: Primary Title */}
      <div style={{ fontSize: 15, fontWeight: 600, color: '#111827', marginBottom: 2 }}>
        {primaryTitle}
      </div>

      {/* Row 3: Definition Name */}
      <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 8 }}>
        {run.definitionName || run.definitionId}
      </div>

      {/* Row 4: Meta row */}
      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: '#6B7280', flexWrap: 'wrap', marginBottom: 6 }}>
        {progressText && <span>{progressText}</span>}
        {failedNodeInfo && <span style={{ color: '#DC2626' }}>{failedNodeInfo}</span>}
        {run.approvalSummary.status !== 'not_required' && (
          <span>⍂ 审批: {approvalLabel}</span>
        )}
        <span>{actionText}</span>
      </div>

      {/* Row 5: technical metadata + Time + CTA */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: '#9CA3AF' }}>
          技术信息可在详情查看
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10, color: '#9CA3AF' }}>{timeLabel}</span>
          <span style={{ fontSize: 11, color: '#0F766E', fontWeight: 500 }}>查看详情 ›</span>
        </span>
      </div>
    </div>
  );
};
