/**
 * WorkflowRunHistory — Workflow Center V2 Round 3
 *
 * 运行记录列表，含：
 *   - 状态筛选 tabs（all / running / awaiting_approval / completed / failed / rejected / cancelled）
 *   - 分页（prev / next）
 *   - 手动刷新
 *   - URL 持久化（workflowStatus, workflowPage）
 *   - AbortController 防 race condition
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { listRuns } from '../../api/workflowApi';
import type { RunSummary, WorkflowRunStatus } from '../../types/workflow';
import { RUN_STATUS_LABELS } from '../../types/workflow';
import { WorkflowRunCard } from './WorkflowRunCard';

interface Props {
  onSelectRun: (runId: string) => void;
  onSwitchToTemplates: () => void;
}

const PAGE_SIZE = 20;

/** 筛选 Tab 定义 */
const FILTER_TABS: { key: string; label: string; status?: WorkflowRunStatus }[] = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '运行中', status: 'running' },
  { key: 'awaiting_approval', label: '待审批', status: 'awaiting_approval' },
  { key: 'completed', label: '已完成', status: 'completed' },
  { key: 'failed', label: '失败', status: 'failed' },
  { key: 'rejected', label: '已驳回', status: 'rejected' },
  { key: 'cancelled', label: '已取消', status: 'cancelled' },
];

/** 筛选状态对应的空数据文案 */
const EMPTY_MESSAGES: Record<string, string> = {
  running: '暂无运行中的工作流',
  awaiting_approval: '暂无待审批的工作流',
  completed: '暂无已完成的工作流',
  failed: '暂无失败的工作流',
  rejected: '暂无已驳回的工作流',
  cancelled: '暂无已取消的工作流',
};

function readUrlParam(key: string, fallback: string): string {
  try {
    const p = new URLSearchParams(window.location.search);
    return p.get(key) || fallback;
  } catch { return fallback; }
}

function syncUrl(params: Record<string, string | null>) {
  try {
    const url = new URL(window.location.href);
    for (const [k, v] of Object.entries(params)) {
      if (v === null || v === '' || v === '1') url.searchParams.delete(k);
      else url.searchParams.set(k, v);
    }
    window.history.replaceState({}, '', url.toString());
  } catch { /* ignore */ }
}

export const WorkflowRunHistory: React.FC<Props> = ({ onSelectRun, onSwitchToTemplates }) => {
  // ── URL-derived state ──
  const [statusFilter, setStatusFilterState] = useState<string>(
    () => readUrlParam('workflowStatus', 'all')
  );
  const [page, setPageState] = useState<number>(() => {
    const raw = readUrlParam('workflowPage', '1');
    const n = parseInt(raw, 10);
    return Number.isFinite(n) && n >= 1 ? n : 1;
  });

  const setStatusFilter = useCallback((s: string) => {
    setStatusFilterState(s);
    setPageState(1);
    syncUrl({ workflowStatus: s === 'all' ? null : s, workflowPage: null });
  }, []);

  const setPage = useCallback((p: number) => {
    setPageState(p);
    syncUrl({ workflowPage: p > 1 ? String(p) : null });
  }, []);

  // ── Data state ──
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const loadRuns = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    const offset = (page - 1) * PAGE_SIZE;

    try {
      const params: Record<string, unknown> = { limit: PAGE_SIZE, offset };
      if (statusFilter !== 'all') params.status = statusFilter;

      const data = await listRuns({
        status: statusFilter !== 'all' ? statusFilter : undefined,
        limit: PAGE_SIZE,
        offset,
      });

      // Guard: only update if this request wasn't aborted
      if (controller.signal.aborted) return;

      setRuns(data.runs);
      setTotal(data.total);

      // Auto-correct page if beyond max
      const maxPage = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
      if (page > maxPage) {
        setPage(maxPage);
      }
    } catch (e: unknown) {
      if (controller.signal.aborted) return;
      setError(e instanceof Error ? e.message : '加载失败');
      setRuns([]);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [statusFilter, page]);

  // ── Load on mount and when deps change ──
  useEffect(() => {
    loadRuns();
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [loadRuns, refreshKey]);

  const handleRefresh = useCallback(() => {
    setRefreshKey(k => k + 1);
  }, []);

  // ── Derived ──
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const offset = (page - 1) * PAGE_SIZE;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + runs.length, total);
  const activeFilterKey = statusFilter === 'all' ? 'all' :
    FILTER_TABS.find(t => t.status === statusFilter)?.key || 'all';
  const emptyMessage = statusFilter !== 'all'
    ? (EMPTY_MESSAGES[statusFilter] || `暂无${statusFilter}的工作流`)
    : '暂无运行记录';

  // ═════════════════════════════════════════════════════════════════════
  // Render
  // ═════════════════════════════════════════════════════════════════════
  return (
    <div>
      {/* ── Filter toolbar ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {FILTER_TABS.map(tab => (
            <button key={tab.key} onClick={() => setStatusFilter(tab.status || 'all')}
              style={{
                padding: '4px 12px', borderRadius: 14, fontSize: 12,
                fontWeight: activeFilterKey === tab.key ? 600 : 400,
                background: activeFilterKey === tab.key ? '#0F766E' : '#F3F4F6',
                color: activeFilterKey === tab.key ? '#FFF' : '#6B7280',
                border: 'none', cursor: 'pointer', transition: 'all 0.15s',
                whiteSpace: 'nowrap',
              }}>
              {tab.label}
            </button>
          ))}
        </div>
        <button onClick={handleRefresh}
          style={{
            padding: '4px 12px', borderRadius: 6, fontSize: 12,
            background: '#FFF', color: '#6B7280',
            border: '1px solid #E5E7EB', cursor: 'pointer',
          }}>
          ⟳ 刷新
        </button>
      </div>

      {/* ── Page info ── */}
      {!loading && !error && total > 0 && (
        <div style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 8 }}>
          当前 {rangeStart}-{rangeEnd} / {total}
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF', fontSize: 13 }}>
          加载运行记录...
        </div>
      )}

      {/* ── Error ── */}
      {!loading && error && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ fontSize: 13, color: '#DC2626', marginBottom: 12 }}>运行记录加载失败</div>
          <div style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 12 }}>{error}</div>
          <button onClick={handleRefresh}
            style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12, color: '#374151' }}>
            重新加载
          </button>
        </div>
      )}

      {/* ── Empty ── */}
      {!loading && !error && runs.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ fontSize: 14, color: '#6B7280', marginBottom: 8 }}>{emptyMessage}</div>
          {statusFilter === 'all' ? (
            <>
              <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 16 }}>
                从"工作流模板"中启动一个流程后，运行记录会显示在这里。
              </div>
              <button onClick={onSwitchToTemplates}
                style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #0F766E', background: '#F0FDFA', cursor: 'pointer', fontSize: 12, color: '#0F766E' }}>
                查看工作流模板
              </button>
            </>
          ) : (
            <button onClick={() => setStatusFilter('all')}
              style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12, color: '#374151', marginTop: 12 }}>
              查看全部
            </button>
          )}
        </div>
      )}

      {/* ── Run Cards ── */}
      {!loading && !error && runs.length > 0 && (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {runs.map(run => (
              <WorkflowRunCard key={run.runId} run={run} onClick={onSelectRun} />
            ))}
          </div>

          {/* ── Pagination ── */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, padding: '16px 0 4px' }}>
              <button onClick={() => setPage(page - 1)} disabled={page <= 1}
                style={{ padding: '4px 14px', borderRadius: 6, border: '1px solid #E5E7EB', background: page <= 1 ? '#F9FAFB' : '#FFF', color: page <= 1 ? '#D1D5DB' : '#374151', cursor: page <= 1 ? 'not-allowed' : 'pointer', fontSize: 12 }}>
                ← 上一页
              </button>
              <span style={{ fontSize: 12, color: '#6B7280' }}>
                第 {page} / {totalPages} 页
              </span>
              <button onClick={() => setPage(page + 1)} disabled={page >= totalPages}
                style={{ padding: '4px 14px', borderRadius: 6, border: '1px solid #E5E7EB', background: page >= totalPages ? '#F9FAFB' : '#FFF', color: page >= totalPages ? '#D1D5DB' : '#374151', cursor: page >= totalPages ? 'not-allowed' : 'pointer', fontSize: 12 }}>
                下一页 →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};
