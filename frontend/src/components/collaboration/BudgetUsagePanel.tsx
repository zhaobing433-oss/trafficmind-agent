/** 预算使用面板 */
import type { CollaborationBudgetUsage } from '../../types/collaboration';

export default function BudgetUsagePanel({ budget, failedAgents }: { budget: CollaborationBudgetUsage; failedAgents: string[] }) {
  const totalCalls = Object.values(budget.usedAgentCalls || {}).reduce((a, b) => a + b, 0);
  const totalRetries = Object.values(budget.usedRetries || {}).reduce((a, b) => a + b, 0);
  const maxCallsOk = totalCalls < budget.maxAgentCalls * 3;

  return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: '#111827' }}>执行预算</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
        <div>Agent 调用: {totalCalls}/{budget.maxAgentCalls}</div>
        <div style={{ color: maxCallsOk ? '#6B7280' : '#EF4444' }}>重试次数: {totalRetries}/{budget.maxRetries}</div>
        <div>最大 Agent: {budget.maxAgents}</div>
        <div>超时: {budget.maxTotalSeconds}s</div>
        {failedAgents.length > 0 && (
          <div style={{ gridColumn: '1/-1', color: '#EF4444', fontWeight: 500 }}>
            失败 Agent: {failedAgents.join(', ')}
          </div>
        )}
      </div>
    </div>
  );
}
