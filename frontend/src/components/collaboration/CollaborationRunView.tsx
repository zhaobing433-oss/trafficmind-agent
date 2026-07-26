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
import MemoryTracePanel from './MemoryTracePanel';
import MemoryPanelErrorBoundary from './MemoryPanelErrorBoundary';

function safeArray<T>(v: unknown): T[] {
  if (Array.isArray(v)) return v as T[];
  return [];
}

function safeObj(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object' && !Array.isArray(v)) return v as Record<string, unknown>;
  return {};
}

export default function CollaborationRunView({ run }: { run: CollaborationRun }) {
  if (!run?.runId) return <div style={{ padding: 20, color: '#9CA3AF', fontSize: 13, textAlign: 'center' }}>等待协同分析启动...</div>;

  const selectedAgents = safeArray<string>(run.selectedAgents);
  const skippedAgents = safeArray<string>(run.skippedAgents);
  const agentResults = safeObj(run.agentResults);
  const agentEntries = Object.entries(agentResults);
  const isTerminal = ['completed', 'partial_success', 'failed', 'interrupted', 'requires_human_review'].includes(run.status);

  return (
    <div style={{ display: 'grid', gap: 12, fontSize: 13 }}>
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
          {selectedAgents.map(a => <span key={a} style={{ background: '#F0FDFA', borderRadius: 8, padding: '2px 8px', fontSize: 11, color: '#0F766E' }}>{a}</span>)}
          {skippedAgents.length > 0 && <span style={{ color: '#9CA3AF', fontSize: 11 }}>跳过: {skippedAgents.join(', ')}</span>}
        </div>
      </div>

      {run.userQuery && (
        <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
          <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 13, color: '#111827' }}>上下文策略</div>
          <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>本轮问题: {(run.userQuery || '').slice(0, 120)}{(run.userQuery || '').length > 120 ? '...' : ''}</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 6, background: run.contextPolicy === 'fresh_event' ? '#ECFDF5' : run.contextPolicy === 'continue_event' ? '#EFF6FF' : '#FFFBEB', color: run.contextPolicy === 'fresh_event' ? '#065F46' : run.contextPolicy === 'continue_event' ? '#1E40AF' : '#92400E', fontWeight: 600 }}>
              策略: {{ fresh_event: '全新事件', continue_event: '延续事件', follow_up: '追问' }[String(run.contextPolicy || 'fresh_event')] || run.contextPolicy}
            </span>
            {run.fieldSources && typeof run.fieldSources === 'object' && (
              <>
                {Object.entries(run.fieldSources).filter(([, v]) => v === 'current_message').length > 0 && (
                  <span style={{ fontSize: 10, color: '#0F766E', background: '#F0FDFA', padding: '2px 6px', borderRadius: 4 }}>
                    当前消息: {Object.entries(run.fieldSources).filter(([, v]) => v === 'current_message').map(([k]) => k).join(', ')}
                  </span>
                )}
                {Object.entries(run.fieldSources).filter(([, v]) => v === 'missing').length > 0 && (
                  <span style={{ fontSize: 10, color: '#9CA3AF', background: '#F9FAFB', padding: '2px 6px', borderRadius: 4 }}>
                    缺失: {Object.entries(run.fieldSources).filter(([, v]) => v === 'missing').map(([k]) => k).join(', ')}
                  </span>
                )}
                {Object.entries(run.fieldSources).filter(([, v]) => v === 'explicit_previous_reference').length > 0 && (
                  <span style={{ fontSize: 10, color: '#1E40AF', background: '#EFF6FF', padding: '2px 6px', borderRadius: 4 }}>
                    继承: {Object.entries(run.fieldSources).filter(([, v]) => v === 'explicit_previous_reference').map(([k]) => k).join(', ')}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {run.previousRunContext != null && typeof run.previousRunContext === 'object' && 'runId' in (run.previousRunContext as object) && (
        <div style={{ background: '#FFFBEB', borderRadius: 14, padding: 14, border: '1px solid #F59E0B20', borderLeft: '3px solid #F59E0B' }}>
          <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 12, color: '#92400E' }}>上一轮上下文（仅供参考，不合并到本轮分析）</div>
          <div style={{ fontSize: 10, color: '#92400E', marginBottom: 4 }}>
            Run: {String((run.previousRunContext as Record<string,unknown>).runId).slice(0, 20)}...
          </div>
          <div style={{ fontSize: 11, color: '#78350F' }}>{String((run.previousRunContext as Record<string,unknown>).summary || '').slice(0, 150)}</div>
        </div>
      )}

      <CollaborationDagView tasks={safeArray(run.tasks)} />

      {agentEntries.length > 0 && (
        <div style={{ display: 'grid', gap: 8 }}>
          {agentEntries.map(([name, result]) => (
            <AgentExecutionCard key={name} agentName={name} result={result as CollaborationRun['agentResults'][string]} />
          ))}
        </div>
      )}

      <ConflictPanel conflicts={safeArray(run.conflicts)} />

      <BudgetUsagePanel budget={run.budgetUsage} failedAgents={safeArray<string>(run.failedAgents)} />

      {(run.fusionSummary || run.finalDecision) && <FusionDecisionView run={run} />}
      <MemoryPanelErrorBoundary runId={run.runId}>
        <MemoryTracePanel runId={run.runId} visible={run.status === 'completed' || run.status === 'partial_success'} />
      </MemoryPanelErrorBoundary>
    </div>
  );
}
