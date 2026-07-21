/**
 * 协作运行总览 — Phase 9.5
 */
import type { CollaborationRun } from '../../types/collaboration';
import { STATUS_LABELS, AGENT_ROLES } from '../../types/collaboration';
import CollaborationDagView from './CollaborationDagView';
import AgentExecutionCard from './AgentExecutionCard';
import ConflictPanel from './ConflictPanel';
import BudgetUsagePanel from './BudgetUsagePanel';
import FusionDecisionView from './FusionDecisionView';

export default function CollaborationRunView({ run }: { run: CollaborationRun }) {
  if (!run.runId) return <div style={{ padding: 20, color: '#9CA3AF', fontSize: 13, textAlign: 'center' }}>等待协同分析启动...</div>;

  const isTerminal = ['completed', 'partial_success', 'failed', 'interrupted', 'requires_human_review'].includes(run.status);

  return (
    <div style={{ display: 'grid', gap: 12, fontSize: 13 }}>
      {/* Overview */}
      <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <strong style={{ fontSize: 15, color: '#111827' }}>协同运行</strong>
            <span style={{ color: '#9CA3AF', fontSize: 11, marginLeft: 8 }}>{run.runId}</span>
          </div>
          <span style={{
            padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600,
            background: isTerminal ? (run.status === 'completed' ? '#ECFDF5' : run.status === 'failed' ? '#FEF2F2' : '#FFFBEB') : '#EFF6FF',
            color: isTerminal ? (run.status === 'completed' ? '#065F46' : run.status === 'failed' ? '#991B1B' : '#92400E') : '#1E40AF',
          }}>{STATUS_LABELS[run.status] || run.status}</span>
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 6, fontSize: 11, color: '#9CA3AF', flexWrap: 'wrap' }}>
          <span>引擎: {run.executionEngine}</span>
          <span>协议: v{run.protocolVersion}</span>
          {run.startedAt && <span>开始: {run.startedAt}</span>}
          {run.completedAt && <span>完成: {run.completedAt}</span>}
          {run.degraded && <span style={{ color: '#F59E0B' }}>⚠ 已降级: {run.fallbackReason}</span>}
          {run.requiresHumanReview && <span style={{ color: '#EF4444', fontWeight: 600 }}>⚠ 需人工审核</span>}
        </div>
        <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {run.selectedAgents.map(a => <span key={a} style={{ background: '#F0FDFA', borderRadius: 8, padding: '2px 8px', fontSize: 11, color: '#0F766E' }}>{a}</span>)}
          {run.skippedAgents.length > 0 && <span style={{ color: '#9CA3AF', fontSize: 11 }}>跳过: {run.skippedAgents.join(', ')}</span>}
        </div>
      </div>

      {/* DAG */}
      <CollaborationDagView tasks={run.tasks} />

      {/* Agent Results */}
      {Object.keys(run.agentResults).length > 0 && (
        <div style={{ display: 'grid', gap: 8 }}>
          {Object.entries(run.agentResults).map(([name, result]) => (
            <AgentExecutionCard key={name} agentName={name} result={result} />
          ))}
        </div>
      )}

      {/* Conflicts */}
      <ConflictPanel conflicts={run.conflicts} />

      {/* Budget */}
      <BudgetUsagePanel budget={run.budgetUsage} failedAgents={run.failedAgents} />

      {/* Fusion */}
      {run.fusionSummary && <FusionDecisionView run={run} />}
    </div>
  );
}
