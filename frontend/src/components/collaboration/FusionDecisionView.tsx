/** 最终融合结果 */
import type { CollaborationRun } from '../../types/collaboration';

function safeArray<T>(v: unknown): T[] {
  if (Array.isArray(v)) return v as T[];
  return [];
}

function safeString(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object') {
    const obj = v as Record<string,unknown>;
    return String(obj.fusionSummary || obj.fusion_summary || obj.summary || '');
  }
  return String(v || '');
}

export default function FusionDecisionView({ run }: { run: CollaborationRun }) {
  const failedAgents = safeArray<string>(run.failedAgents);
  const limitations = safeArray<string>(run.limitations);
  const fusionSummary = run.fusionSummary || safeString(run.finalDecision);

  const statusBanner = () => {
    if (run.status === 'failed') return { bg: '#FEF2F2', color: '#991B1B', text: '协同分析执行失败' };
    if (run.status === 'interrupted') return { bg: '#FFF7ED', color: '#9A3412', text: '运行因服务中断未完整完成。已完成步骤见下方。' };
    if (run.status === 'partial_success') return { bg: '#FFFBEB', color: '#92400E', text: `部分 Agent 未能完成: ${failedAgents.join(', ')}。结果仅供参考。` };
    if (run.requiresHumanReview) return { bg: '#FEF2F2', color: '#991B1B', text: '⚠ 需要人工审核 — 以上建议不能作为确定执行命令' };
    return null;
  };

  const banner = statusBanner();

  return (
    <div style={{ background: '#FFF', borderRadius: 14, padding: 14, border: '1px solid #0F766E', borderLeft: '4px solid #0F766E' }}>
      <div style={{ fontWeight: 700, fontSize: 14, color: '#111827', marginBottom: 8 }}>融合决策</div>

      {banner && (
        <div style={{ background: banner.bg, borderRadius: 10, padding: '8px 12px', marginBottom: 10, fontSize: 12, color: banner.color, fontWeight: 600 }}>
          {banner.text}
        </div>
      )}

      {fusionSummary && (
        <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, color: '#374151', lineHeight: 1.7, marginBottom: 8 }}>
          {fusionSummary}
        </div>
      )}

      {failedAgents.length > 0 && (
        <div style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 4 }}>失败 Agent: {failedAgents.join(', ')}</div>
      )}
      {limitations.length > 0 && (
        <div style={{ fontSize: 11, color: '#9CA3AF' }}>限制说明: {limitations.join('; ')}</div>
      )}
    </div>
  );
}
