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

/** Show value or "—" if null/undefined */
function showNum(v: number | null | undefined): string {
  if (v == null) return '—';
  return String(v);
}

export default function BudgetUsagePanel({ budget, failedAgents }: { budget?: CollaborationBudgetUsage | Record<string,unknown>; failedAgents?: unknown }) {
  if (!budget || typeof budget !== 'object') {
    return <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB', fontSize: 12, color: '#6B7280' }}>预算数据不可用</div>;
  }

  const b = budget as Record<string,unknown>;

  // Normalize snake_case / camelCase
  const maxDomainAgents = (b.maxDomainAgents ?? b.max_agents ?? b.maxAgents ?? b.maxAgents_key_fallback ?? null) as number | null;
  const maxAgentCalls = (b.maxAgentCalls ?? b.max_agent_calls ?? b.maxAgentCalls ?? null) as number | null;
  const maxRetries = (b.maxRetries ?? b.max_retries ?? null) as number | null;
  const maxTotalSeconds = (b.maxTotalSeconds ?? b.max_total_seconds ?? null) as number | null;

  const usedCalls = safeObj(b.usedAgentCalls ?? b.used_agent_calls);
  const usedRetries = safeObj(b.usedRetries ?? b.used_retries);

  const totalCalls = Object.values(usedCalls).reduce((a, b2) => a + b2, 0);
  const totalRetries = Object.values(usedRetries).reduce((a, b2) => a + b2, 0);
  const agents = safeArray(failedAgents);

  return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #E5E7EB' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: '#111827' }}>执行预算</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
        <div>领域Agent: {totalCalls} / 最大 {showNum(maxDomainAgents)}</div>
        <div>重试次数: {totalRetries} / {showNum(maxRetries)}</div>
        <div>每Agent调用上限: {showNum(maxAgentCalls)}</div>
        <div>超时: {showNum(maxTotalSeconds)}s</div>
        {Object.keys(usedCalls).length > 0 && (
          <div style={{ gridColumn: '1/-1', fontSize: 10, color: '#6B7280' }}>
            调用明细: {Object.entries(usedCalls).map(([k, v]) => `${k}×${v}`).join(' · ')}
          </div>
        )}
        {agents.length > 0 && (
          <div style={{ gridColumn: '1/-1', color: '#EF4444', fontWeight: 500 }}>
            失败 Agent: {agents.join(', ')}
          </div>
        )}
      </div>
    </div>
  );
}
