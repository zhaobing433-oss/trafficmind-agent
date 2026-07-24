/** Agent 执行卡片 */
import type { CollaborationAgentResult } from '../../types/collaboration';
import { AGENT_ROLES } from '../../types/collaboration';

export default function AgentExecutionCard({ agentName, result }: { agentName: string; result: CollaborationAgentResult }) {
  return (
    <div style={{ background: '#F0FDFA', borderRadius: 14, padding: 12, border: '1px solid #0F766E15' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <strong style={{ color: '#0F766E', fontSize: 13 }}>{agentName}</strong>
          <span style={{ color: '#6B7280', fontSize: 11, marginLeft: 6 }}>{AGENT_ROLES[agentName] || ''}</span>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{
            padding: '2px 8px', borderRadius: 8, fontSize: 10, fontWeight: 600,
            background: result.urgency === 'high' || result.urgency === 'critical' ? '#FEF2F2' : '#FFFBEB',
            color: result.urgency === 'high' || result.urgency === 'critical' ? '#991B1B' : '#92400E',
          }}>{result.urgency}</span>
          {result.confidence > 0 && <span style={{ fontSize: 10, color: '#9CA3AF' }}>置信度 {Math.round(result.confidence * 100)}%</span>}
          {result.attempt > 1 && <span style={{ fontSize: 10, color: '#9CA3AF' }}>#{result.attempt}</span>}
          {result.duration > 0 && <span style={{ fontSize: 10, color: '#9CA3AF' }}>{result.duration}ms</span>}
        </div>
      </div>
      {result.findings.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {result.findings.map((f, i) => <div key={i} style={{ fontSize: 12, color: '#374151', padding: '1px 0' }}>- {f}</div>)}
        </div>
      )}
      {result.suggestion && <div style={{ fontSize: 12, color: '#0F766E', marginTop: 4, fontWeight: 600 }}>建议: {result.suggestion}</div>}
      {result.errorCode && <div style={{ fontSize: 10, color: '#EF4444', marginTop: 2 }}>错误: {result.errorCode} - {result.errorMessage}</div>}
    </div>
  );
}
