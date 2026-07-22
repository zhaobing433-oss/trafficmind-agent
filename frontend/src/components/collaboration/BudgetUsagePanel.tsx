/** 预算使用面板 */
import type { CollaborationBudgetUsage } from '../../types/collaboration';

function safeObj(v: unknown): Record<string, number> {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const out: Record<string, number> = {};
    for (const [k, val] of Object.entries(v as Record<string,unknown>)) {
      out[k] = Number(val) || 0;
    }
    return out;
  }
  return {};
}

function safeArray(v: unknown): string[] {
  if (Array.isArray(v)) return v as string[];
  return [];
}

export default function BudgetUsagePanel({ budget, failedAgents }: { budget?: CollaborationBudgetUsage; failedAgents?: unknown }) {
  if (!budget || typeof budget !== 'object') {
    return <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB', fontSize: 12, color: '#6B7280' }}>预算数据不可用</div>;
  }

  const usedAgentCalls = safeObj(budget?.usedAgentCalls);
  const usedRetries = safeObj(budget?.usedRetries);
  const totalCalls = Object.values(usedAgentCalls).reduce((a, b) => a + b, 0);
  const totalRetries = Object.values(usedRetries).reduce((a, b) => a + b, 0);
  const maxCalls = Number(budget?.maxAgentCalls) || 0;
  const maxRetries = Number(budget?.maxRetries) || 0;
  const maxAgents = Number(budget?.maxAgents) || 0;
  const maxTotalSeconds = Number(budget?.maxTotalSeconds) || 0;
  const maxCallsOk = totalCalls < maxCalls * 3;
  const agents = safeArray(failedAgents);

  return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: '#111827' }}>执行预算</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
        <div>Agent 调用: {totalCalls}/{maxCalls}</div>
        <div style={{ color: maxCallsOk ? '#6B7280' : '#EF4444' }}>重试次数: {totalRetries}/{maxRetries}</div>
        <div>最大 Agent: {maxAgents}</div>
        <div>超时: {maxTotalSeconds}s</div>
        {agents.length > 0 && (
          <div style={{ gridColumn: '1/-1', color: '#EF4444', fontWeight: 500 }}>
            失败 Agent: {agents.join(', ')}
          </div>
        )}
      </div>
    </div>
  );
}
