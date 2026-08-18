/** Phase17 Plan Center — 最小 planning / trajectory observability */

import { useEffect, useMemo, useState } from 'react';
import { listPlans, getPlan, getPlanDiff, getTrajectory, listObservations } from '../../api/planningApi';
import type {
  PlanListItem, PlanRunSummary, TrajectoryResponse, VersionDiff, ObservationItem,
} from '../../types/planning';

const STATUS_COLORS: Record<string, string> = {
  completed: '#16A34A', failed: '#DC2626', running: '#2563EB', pending: '#9CA3AF',
  awaiting_approval: '#D97706', paused: '#9CA3AF', cancelled: '#6B7280', rejected: '#DC2626',
};

const OBSERVATION_LABELS: Record<string, string> = {
  tool_denied: '工具拒绝', approval_rejected: '审批驳回', budget_exhausted: '预算耗尽',
  loop_detected: '循环终止', unknown_outcome: '结果未知', retry_exhausted: '重试耗尽',
};

function statusLabel(s: string): string {
  const m: Record<string, string> = {
    completed: '完成', failed: '失败', running: '运行中', pending: '待执行',
    awaiting_approval: '待审批', paused: '暂停', cancelled: '已取消', rejected: '已驳回',
  };
  return m[s] || s;
}

export interface PlanCenterProps {
  planId: string | null;
  rootRunId: string | null;
  fromVersion: number | null;
  toVersion: number | null;
  onPlanSelect: (planId: string) => void;
  onRootRunIdChange: (rootRunId: string | null) => void;
  onDiffChange: (fromVersion: number | null, toVersion: number | null) => void;
  onOpenWorkflowRun: (runId: string) => void;
}

export function PlanCenter(props: PlanCenterProps) {
  if (!props.planId) {
    return <PlanList onSelect={props.onPlanSelect} />;
  }
  return <PlanDetail {...props} />;
}

// ── Plan List ───────────────────────────────────────────────────────────────

function PlanList({ onSelect }: { onSelect: (id: string) => void }) {
  const [items, setItems] = useState<PlanListItem[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 20;

  useEffect(() => {
    listPlans({ page, pageSize }).then(r => { setItems(r.plans); setTotal(r.total); }).catch(() => {});
  }, [page]);

  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>Plan Center</h2>
      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 12px' }}>自适应计划 · 执行血缘 · 重规划轨迹 · 预算与恢复</p>
      {items.length === 0 ? <Empty text="暂无计划" /> : (
        <div style={{ display: 'grid', gap: 8 }}>
          {items.map(p => (
            <button key={p.planId} onClick={() => onSelect(p.planId)}
              style={{ textAlign: 'left', background: '#FFF', borderRadius: 12, padding: '12px 16px', border: '1px solid #E5E7EB', cursor: 'pointer' }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#111827' }}>{p.goal || '未命名计划'}</div>
              <div style={{ fontSize: 12, color: '#6B7280', marginTop: 4 }}>
                类型 {p.goalType || '—'} · 版本 v{p.latestVersion} · 执行 {p.executionCount} 次 · 重规划 {p.replanCount} 次
              </div>
              <div style={{ fontSize: 12, color: p.latestExecutionStatus ? STATUS_COLORS[p.latestExecutionStatus] || '#6B7280' : '#9CA3AF', marginTop: 4 }}>
                {p.latestExecutionStatus ? `最近状态：${statusLabel(p.latestExecutionStatus)}` : '未执行'} · 更新于 {p.updatedAt ? new Date(p.updatedAt).toLocaleString() : '—'}
              </div>
            </button>
          ))}
        </div>
      )}
      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 12 }}>
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} style={pagerBtn(page <= 1)}>上一页</button>
          <span style={{ fontSize: 12, color: '#6B7280', alignSelf: 'center' }}>{page} / {pages}</span>
          <button disabled={page >= pages} onClick={() => setPage(p => p + 1)} style={pagerBtn(page >= pages)}>下一页</button>
        </div>
      )}
    </div>
  );
}

function pagerBtn(disabled: boolean): React.CSSProperties {
  return { padding: '4px 12px', borderRadius: 8, border: '1px solid #E5E7EB', background: disabled ? '#F3F4F6' : '#FFF', cursor: disabled ? 'not-allowed' : 'pointer', fontSize: 12, color: disabled ? '#9CA3AF' : '#111827' };
}

function Empty({ text }: { text: string }) {
  return <div style={{ background: '#FFF', borderRadius: 12, padding: 24, border: '1px solid #E5E7EB', textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{text}</div>;
}

// ── Plan Detail ─────────────────────────────────────────────────────────────

function PlanDetail(props: PlanCenterProps) {
  const { planId, rootRunId, fromVersion, toVersion } = props;
  const [plan, setPlan] = useState<{ goal: string; goalType: string; version: number; planFingerprint: string; definitionStatus: string; createdAt: string } | null>(null);
  const [runs, setRuns] = useState<PlanRunSummary[]>([]);
  const [trajectory, setTrajectory] = useState<TrajectoryResponse | null>(null);
  const [observations, setObservations] = useState<ObservationItem[]>([]);

  useEffect(() => {
    getPlan(planId!).then(r => { setPlan(r.plan); setRuns(r.runs); }).catch(() => {});
  }, [planId]);

  // 分组 rootRunId
  const lineages = useMemo(() => {
    const map = new Map<string, PlanRunSummary[]>();
    for (const r of runs) {
      const root = r.rootRunId || r.runId;
      if (!map.has(root)) map.set(root, []);
      map.get(root)!.push(r);
    }
    return Array.from(map.entries());
  }, [runs]);

  const activeRoot = rootRunId || (lineages.length > 0 ? lineages[lineages.length - 1][0] : null);

  useEffect(() => {
    if (activeRoot) {
      getTrajectory(activeRoot).then(setTrajectory).catch(() => setTrajectory(null));
    } else {
      setTrajectory(null);
    }
  }, [activeRoot]);

  useEffect(() => {
    if (activeRoot) {
      listObservations(activeRoot).then(r => setObservations(r.observations)).catch(() => setObservations([]));
    }
  }, [activeRoot]);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <button onClick={() => props.onPlanSelect('')} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 13, color: '#0F766E', padding: 0 }}>← 计划列表</button>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', margin: 0 }}>{plan?.goal || '计划详情'}</h2>
      </div>
      <p style={{ fontSize: 12, color: '#6B7280', margin: '0 0 12px' }}>
        planId {planId} · v{plan?.version} · {plan?.goalType || '—'}
        {plan?.planFingerprint ? <span style={{ fontFamily: 'monospace' }}> · fp {plan.planFingerprint.slice(0, 10)}</span> : null}
      </p>

      {lineages.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
          {lineages.map(([root]) => (
            <button key={root} onClick={() => props.onRootRunIdChange(root)}
              style={{ padding: '4px 10px', borderRadius: 10, border: '1px solid #E5E7EB', background: root === activeRoot ? '#F0FDFA' : '#FFF', cursor: 'pointer', fontSize: 12 }}>
              lineage {root.slice(0, 12)}
            </button>
          ))}
        </div>
      )}

      <ExecutionLineage runs={runs.filter(r => (r.rootRunId || r.runId) === activeRoot)} onOpenRun={props.onOpenWorkflowRun} />
      <BudgetPanel runs={runs.filter(r => (r.rootRunId || r.runId) === activeRoot)} />
      <ObservationTimeline observations={observations} />
      <TrajectoryPanel trajectory={trajectory} />
      <DiffPanel planId={planId!} versions={runs.map(r => r.version)} fromVersion={fromVersion} toVersion={toVersion} onDiffChange={props.onDiffChange} />
    </div>
  );
}

// ── Execution Lineage ───────────────────────────────────────────────────────

function orderLineage(runs: PlanRunSummary[]): PlanRunSummary[] {
  // 按 parent → child（replannedFromRunId → replannedToRunId）排序，root 在前
  const byId = new Map(runs.map(r => [r.runId, r]));
  const roots = runs.filter(r => !r.replannedFromRunId);
  const ordered: PlanRunSummary[] = [];
  const seen = new Set<string>();
  const walk = (runId: string) => {
    if (!runId || seen.has(runId)) return;
    const r = byId.get(runId);
    if (!r) return;
    seen.add(runId);
    ordered.push(r);
    if (r.replannedToRunId) walk(r.replannedToRunId);
  };
  roots.forEach(r => walk(r.runId));
  // 兜底：未连入链的 run（孤儿/独立）按 version ASC 追加
  for (const r of runs) if (!seen.has(r.runId)) ordered.push(r);
  return ordered;
}

function ExecutionLineage({ runs, onOpenRun }: { runs: PlanRunSummary[]; onOpenRun: (id: string) => void }) {
  const ordered = orderLineage(runs);
  if (ordered.length === 0) return <Panel title="执行血缘"><Empty text="暂无执行" /></Panel>;
  return (
    <Panel title="执行血缘">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {ordered.map((r, i) => {
          const replanned = r.status === 'failed' && r.terminationReason === 'replanned';
          return (
            <div key={r.runId}>
              <div style={{ background: '#F9FAFB', borderRadius: 10, padding: '8px 12px', border: '1px solid #E5E7EB', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>v{r.version}</span>
                <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 8, background: replanned ? '#FEF3C7' : '#F3F4F6', color: replanned ? '#B45309' : STATUS_COLORS[r.status] || '#374151' }}>
                  {replanned ? 'Replanned（原 run 失败）' : statusLabel(r.status)}
                </span>
                {replanned && <span style={{ fontSize: 11, color: '#9CA3AF' }}>（Underlying status: Failed）</span>}
                {r.terminationReason && !replanned && <span style={{ fontSize: 11, color: '#6B7280' }}>{r.terminationReason}</span>}
                <span style={{ flex: 1 }} />
                <button onClick={() => onOpenRun(r.runId)} style={{ fontSize: 11, color: '#0F766E', border: 'none', background: 'none', cursor: 'pointer' }}>打开 Workflow Run →</button>
              </div>
              {i < ordered.length - 1 && <div style={{ textAlign: 'center', color: '#9CA3AF', fontSize: 11, padding: '2px 0' }}>↓ 重规划 / 续接</div>}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ── Observation Timeline ────────────────────────────────────────────────────

function ObservationTimeline({ observations }: { observations: ObservationItem[] }) {
  const sorted = [...observations].sort((a, b) => (a.timestamp < b.timestamp ? -1 : 1));
  return (
    <Panel title={`观察时间线（${sorted.length}）`}>
      {sorted.length === 0 ? <Empty text="暂无观察" /> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {sorted.map((o, i) => {
            const label = OBSERVATION_LABELS[o.type];
            const isWarn = ['unknown_outcome', 'budget_exhausted', 'loop_detected', 'tool_denied', 'approval_rejected', 'retry_exhausted'].includes(o.type);
            return (
              <div key={o.observationId || i} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid #F3F4F6', display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ color: isWarn ? '#DC2626' : '#6B7280', fontWeight: isWarn ? 600 : 400 }}>{label || o.type}</span>
                {o.stepId && <span style={{ color: '#9CA3AF' }}>{o.stepId}</span>}
                {o.failureReason && <span style={{ color: '#6B7280' }}>{o.failureReason}</span>}
                {o.type === 'unknown_outcome' && <span style={{ color: '#DC2626', fontWeight: 600 }}>（需人工复核）</span>}
                <span style={{ flex: 1 }} />
                <span style={{ color: '#9CA3AF', fontSize: 11 }}>{o.timestamp ? new Date(o.timestamp).toLocaleTimeString() : ''}</span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

// ── Trajectory Panel ────────────────────────────────────────────────────────

function TrajectoryPanel({ trajectory }: { trajectory: TrajectoryResponse | null }) {
  if (!trajectory) return <Panel title="轨迹指标"><Empty text="暂无轨迹" /></Panel>;
  const m = trajectory.metrics;
  const items = [
    ['最终结果', trajectory.finalOutcome ? statusLabel(trajectory.finalOutcome) : '—'],
    ['版本数', String(m.revisionCount)],
    ['重规划', String(m.replanCount)],
    ['恢复率', m.recoveryRate === null ? 'N/A（无恢复）' : `${Math.round(m.recoveryRate * 100)}%`],
    ['平均恢复时长', m.averageTimeToRecoverySeconds === null ? 'N/A' : `${m.averageTimeToRecoverySeconds}s`],
    ['预算耗尽', String(m.budgetExhaustions)],
    ['循环终止', String(m.loopStops)],
    ['工具拒绝', String(m.toolDenials)],
    ['人工介入', String(m.humanInterventions)],
    ['携带步骤', String(m.carriedForwardCount)],
    ['重复副作用', String(m.duplicateSideEffectCount)],
    ['轨迹长度', String(m.trajectoryLength)],
  ];
  return (
    <Panel title="轨迹指标">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        {items.map(([l, v]) => (
          <div key={l} style={{ background: '#F9FAFB', borderRadius: 8, padding: '8px 10px', border: '1px solid #F3F4F6' }}>
            <div style={{ fontSize: 11, color: '#9CA3AF' }}>{l}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: l === '重复副作用' && m.duplicateSideEffectCount > 0 ? '#DC2626' : '#111827' }}>{v}</div>
          </div>
        ))}
      </div>
      {m.duplicateSideEffectCount > 0 && <div style={{ fontSize: 11, color: '#DC2626', marginTop: 6 }}>⚠ 检测到重复外部副作用</div>}
    </Panel>
  );
}

// ── Budget & Reliability Panel ─────────────────────────────────────────────

function BudgetPanel({ runs }: { runs: PlanRunSummary[] }) {
  const ordered = orderLineage(runs);
  const leaf = ordered[ordered.length - 1];
  const usage = leaf?.budgetUsage || {};
  const limits = leaf?.budgetLimits || {};
  const rows: [string, number, number | undefined][] = [
    ['Steps', usage.stepsUsed ?? 0, limits.maxSteps],
    ['Retries', usage.retriesUsed ?? 0, limits.maxRetries],
    ['Tools', usage.toolCallsUsed ?? 0, limits.maxToolCalls],
    ['Replans', usage.replansUsed ?? 0, limits.maxReplans],
    ['Active time (s)', usage.activeElapsedSeconds ?? 0, limits.maxTotalSeconds],
  ];
  return (
    <Panel title="预算与可靠性">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
        {rows.map(([l, used, max]) => (
          <div key={l} style={{ background: '#F9FAFB', borderRadius: 8, padding: '8px 10px', border: '1px solid #F3F4F6' }}>
            <div style={{ fontSize: 11, color: '#9CA3AF' }}>{l}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#111827' }}>{used} / {max ?? '∞'}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── Diff Panel ──────────────────────────────────────────────────────────────

function DiffPanel({ planId, versions, fromVersion, toVersion, onDiffChange }: {
  planId: string; versions: number[]; fromVersion: number | null; toVersion: number | null; onDiffChange: (f: number | null, t: number | null) => void;
}) {
  const uniq = useMemo(() => Array.from(new Set(versions)).sort((a, b) => a - b), [versions]);
  const defaultTo = uniq.length > 0 ? uniq[uniq.length - 1] : null;
  const defaultFrom = uniq.length > 1 ? uniq[uniq.length - 2] : null;
  // 直接派生 eff from/to（URL prop 优先，否则默认 latest-1 → latest），不引入会 desync 的独立 state
  const effFrom = fromVersion ?? defaultFrom;
  const effTo = toVersion ?? defaultTo;
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (effFrom != null && effTo != null && effFrom !== effTo) {
      let cancelled = false;
      setLoading(true); setError(false);
      getPlanDiff(planId, effFrom, effTo)
        .then(r => { if (!cancelled) setDiff(r); })
        .catch(() => { if (!cancelled) { setDiff(null); setError(true); } })
        .finally(() => { if (!cancelled) setLoading(false); });
      return () => { cancelled = true; };
    }
    setDiff(null);
  }, [planId, effFrom, effTo]);

  const isEmptyDiff = diff !== null && diff.addedSteps.length === 0 && diff.removedSteps.length === 0 && diff.changedSteps.length === 0 && diff.carriedForwardSteps.length === 0;

  return (
    <Panel title="版本对比">
      {uniq.length < 2 ? <Empty text="暂无可比较版本" /> : (
        <div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
            <select value={effFrom != null ? String(effFrom) : ''} onChange={e => onDiffChange(e.target.value ? Number(e.target.value) : null, effTo)} style={sel}>
              {uniq.map(v => <option key={v} value={v}>v{v}</option>)}
            </select>
            <span style={{ color: '#9CA3AF' }}>→</span>
            <select value={effTo != null ? String(effTo) : ''} onChange={e => onDiffChange(effFrom, e.target.value ? Number(e.target.value) : null)} style={sel}>
              {uniq.map(v => <option key={v} value={v}>v{v}</option>)}
            </select>
          </div>
          {loading ? <Empty text="加载版本差异..." /> :
           error ? <Empty text="版本差异加载失败" /> :
           diff === null ? <Empty text="选择版本查看 diff" /> :
           isEmptyDiff ? <Empty text="两个版本结构无差异" /> : (
            <div style={{ fontSize: 12 }}>
              <DiffRow label="新增" items={diff.addedSteps} color="#16A34A" />
              <DiffRow label="移除" items={diff.removedSteps} color="#DC2626" />
              <DiffRow label="变更" items={diff.changedSteps} color="#D97706" />
              <DiffRow label="携带（不重执行）" items={diff.carriedForwardSteps} color="#0F766E" />
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

const sel: React.CSSProperties = { padding: '4px 8px', borderRadius: 8, border: '1px solid #E5E7EB', fontSize: 12 };

function DiffRow({ label, items, color }: { label: string; items: string[]; color: string }) {
  return (
    <div style={{ marginBottom: 4 }}>
      <span style={{ fontWeight: 600, color }}>{label}（{items.length}）</span>
      {items.length > 0 && <span style={{ color: '#6B7280' }}>：{items.join('、')}</span>}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: '#FFF', borderRadius: 12, padding: 14, border: '1px solid #E5E7EB', marginBottom: 12 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: '#111827', marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}
