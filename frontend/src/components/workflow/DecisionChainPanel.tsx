/**
 * DecisionChainPanel — Phase 20 Round 2
 *
 * 决策链面板：唯一数据来源是 GET /workflow/runs/{run_id} 的 decisionProvenance
 * 安全投影（backend/planning/decision_provenance.py，只读、已脱敏）。
 *
 * 绝不：
 *   - 消费 /trace 原始 payload
 *   - 渲染 run.state 原始 JSON
 *   - 渲染 rawPrompt / rawResponse / provider raw text / CoT / memory body /
 *     RAG body / secret / raw action params / failureReason 原始 body /
 *     contextFingerprint / sourceSnapshotDigest
 *
 * 排序是确定性排序（decisionType 秩 + boundaryKey），非时间顺序 → 面板命名「决策链」。
 */
import React, { useEffect, useState } from 'react';
import { getRun } from '../../api/workflowApi';
import type { DecisionProvenanceEntry } from '../../types/workflow';
import { DECISION_TYPE_LABELS } from '../../types/workflow';

interface Props {
  runId: string;
  onOpenChildRun?: (childRunId: string) => void;
  onOpenPlan?: (planId: string) => void;
}

const MAIN_DECISION_ORDER: Record<string, number> = { critic: 0, semantic_replan: 1, assessment: 2 };

const statusColor = (s: string | undefined | null): string => {
  switch (s) {
    case 'COMPLETED': case 'deterministic': return '#16A34A';
    case 'STARTED': return '#D97706';
    case 'unknown': return '#9CA3AF';
    default: return '#6B7280';
  }
};

const yn = (v: boolean | null | undefined): string => (v === true ? '是' : v === false ? '否' : '未记录');
const fmt = (v: string | null | undefined): string => {
  if (v === null || v === undefined || v === '') return '未记录';
  if (v === 'unknown') return '未知';
  return v;
};

export const DecisionChainPanel: React.FC<Props> = ({ runId, onOpenChildRun, onOpenPlan }) => {
  const [entries, setEntries] = useState<DecisionProvenanceEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [definitionId, setDefinitionId] = useState<string>('');
  const [planState, setPlanState] = useState<'checking' | 'is_plan' | 'not_plan' | 'error'>('checking');

  // 数据唯一来源：GET /workflow/runs/{run_id} → decisionProvenance
  useEffect(() => {
    let cancelled = false;
    setEntries(null); setError(null); setPlanState('checking');
    getRun(runId)
      .then(detail => {
        if (cancelled) return;
        const prov = Array.isArray(detail.decisionProvenance) ? detail.decisionProvenance as DecisionProvenanceEntry[] : [];
        setEntries(prov);
        const defId = String((detail.run as Record<string, unknown>).definitionId ?? '');
        setDefinitionId(defId);
        if (defId) {
          // 预先探测 plan 关联：GET /planning/plans/{definitionId}
          // 200 → 是 Plan；404（定义不存在）/ 400（定义存在但无 plan 元数据）→ 不是 Plan；
          // 其余 → 查询失败。绝不 fallback 按 definitionName 猜 Plan。
          fetch(`/api/planning/plans/${encodeURIComponent(defId)}`)
            .then(r => { if (!cancelled) setPlanState(r.ok ? 'is_plan' : (r.status === 404 || r.status === 400) ? 'not_plan' : 'error'); })
            .catch(() => { if (!cancelled) setPlanState('error'); });
        } else {
          setPlanState('not_plan');
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // Phase20 R2：404 → 运行不存在（未找到 / 已删除）。不得 fallback 到 parent 或其它运行。
        const msg = e instanceof Error ? e.message : '';
        setError(/404/.test(msg) ? '未找到 / 已删除' : (msg || '加载失败'));
      });
    return () => { cancelled = true; };
  }, [runId]);

  const renderEntry = (e: DecisionProvenanceEntry, i: number) => {
    const typeLabel = DECISION_TYPE_LABELS[e.decisionType] || '未知决策类型';
    return (
      <div key={`${e.boundaryKey}-${i}`} style={{ background: '#F9FAFB', borderRadius: 8, border: '1px solid #E5E7EB', padding: '10px 12px', marginBottom: 8 }}>
        {/* 主层信息 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>{typeLabel}</span>
          <span style={{ fontSize: 10, padding: '1px 8px', borderRadius: 6, background: '#FFF', color: '#6B7280', border: '1px solid #E5E7EB' }}>plan v{e.planVersion ?? '?'}</span>
          <span style={{ fontSize: 11, color: statusColor(e.decisionStatus), fontWeight: 600 }}>{fmt(e.decisionStatus)}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '2px 12px', fontSize: 11 }}>
          <div><span style={{ color: '#9CA3AF' }}>groundedMode：</span>{fmt(e.groundedMode)}</div>
          <div><span style={{ color: '#9CA3AF' }}>providerCall：</span>{yn(e.providerCall)}</div>
          {e.decisionType === 'critic' && (
            <>
              <div><span style={{ color: '#9CA3AF' }}>建议：</span>{fmt(e.recommendation)}</div>
              <div><span style={{ color: '#9CA3AF' }}>置信度：</span>{e.confidence === null || e.confidence === undefined ? '未记录' : String(e.confidence)}</div>
            </>
          )}
          {e.decisionType === 'semantic_replan' && (
            <>
              <div><span style={{ color: '#9CA3AF' }}>结果：</span>{fmt(e.resultStatus)}</div>
              <div><span style={{ color: '#9CA3AF' }}>Critic 建议：</span>{fmt(e.criticRecommendation)}</div>
              {e.childRunId ? (
                <div style={{ gridColumn: '1 / -1' }}>
                  <span style={{ color: '#9CA3AF' }}>子运行：</span>
                  <code style={{ fontSize: 10, color: '#374151' }}>{e.childRunId}</code>
                  {e.childVersion !== null && e.childVersion !== undefined && <span style={{ color: '#9CA3AF', marginLeft: 6 }}>v{e.childVersion}</span>}
                  {onOpenChildRun && (
                    <button onClick={() => onOpenChildRun(e.childRunId as string)}
                      style={{ marginLeft: 8, padding: '1px 8px', borderRadius: 6, border: '1px solid #99F6E4', background: '#F0FDFA', color: '#0F766E', cursor: 'pointer', fontSize: 10 }}>
                      查看子运行 →
                    </button>
                  )}
                </div>
              ) : (
                <div><span style={{ color: '#9CA3AF' }}>子运行：</span>无</div>
              )}
            </>
          )}
          {e.decisionType === 'assessment' && (
            <>
              <div><span style={{ color: '#9CA3AF' }}>结论：</span>{fmt(e.verdict)}</div>
              <div><span style={{ color: '#9CA3AF' }}>目标达成：</span>{yn(e.goalResolved)}</div>
              <div><span style={{ color: '#9CA3AF' }}>结果：</span>{fmt(e.resultStatus)}</div>
            </>
          )}
        </div>

        {/* 技术详情（折叠） */}
        <details style={{ marginTop: 6 }}>
          <summary style={{ fontSize: 10, color: '#9CA3AF', cursor: 'pointer' }}>技术详情</summary>
          <div style={{ marginTop: 4, fontSize: 10, color: '#6B7280', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div>boundaryKey：<code style={{ color: '#374151' }}>{e.boundaryKey}</code></div>
            <div>rootRunId：<code style={{ color: '#374151' }}>{e.rootRunId}</code></div>
            <div>planVersion：{e.planVersion ?? '未记录'}</div>
            <div>providerClaimed：{yn(e.providerClaimed)}（claim ≠ call，仅声明非实证）</div>
            <div>evidenceRefs：{Array.isArray(e.evidenceRefs) && e.evidenceRefs.length > 0
              ? e.evidenceRefs.map(r => <code key={r} style={{ marginRight: 6, color: '#374151' }}>{r}</code>)
              : '无'}</div>
          </div>
        </details>
      </div>
    );
  };

  return (
    <div style={{ background: '#FFF', borderRadius: 8, border: '1px solid #E5E7EB', padding: 14, marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>决策链</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {definitionId && planState === 'is_plan' && onOpenPlan && (
            <button onClick={() => onOpenPlan(definitionId)}
              style={{ padding: '2px 10px', borderRadius: 6, border: '1px solid #99F6E4', background: '#F0FDFA', color: '#0F766E', cursor: 'pointer', fontSize: 11 }}>
              查看计划 →
            </button>
          )}
          {definitionId && planState === 'not_plan' && (
            <span style={{ fontSize: 10, color: '#9CA3AF' }}>该定义不是 Plan</span>
          )}
          {definitionId && planState === 'error' && (
            <span style={{ fontSize: 10, color: '#9CA3AF' }}>计划关联查询失败</span>
          )}
          <span style={{ fontSize: 10, color: '#9CA3AF' }}>按决策类型排序（非精确时间线）</span>
        </div>
      </div>

      {error ? (
        <div style={{ fontSize: 12, color: '#DC2626', padding: '8px 0' }}>{error === '未找到 / 已删除' ? '未找到 / 已删除' : `决策链加载失败：${error}`}</div>
      ) : entries === null ? (
        <div style={{ fontSize: 12, color: '#9CA3AF', padding: '8px 0' }}>正在加载决策记录…</div>
      ) : entries.length === 0 ? (
        <div style={{ fontSize: 12, color: '#9CA3AF', padding: '8px 0' }}>本次运行未生成决策记录</div>
      ) : (
        [...entries]
          .sort((a, b) => {
            const ra = MAIN_DECISION_ORDER[a.decisionType] ?? 99;
            const rb = MAIN_DECISION_ORDER[b.decisionType] ?? 99;
            if (ra !== rb) return ra - rb;
            return String(a.boundaryKey).localeCompare(String(b.boundaryKey));
          })
          .map(renderEntry)
      )}
    </div>
  );
};
