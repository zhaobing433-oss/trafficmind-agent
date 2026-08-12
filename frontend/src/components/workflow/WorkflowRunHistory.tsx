/**
 * WorkflowRunHistory — Workflow Center V2 Round 2
 *
 * 运行记录列表。获取 GET /workflow/runs 并展示 Run Cards。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { listRuns } from '../../api/workflowApi';
import type { RunSummary } from '../../types/workflow';
import { WorkflowRunCard } from './WorkflowRunCard';

interface Props {
  onSelectRun: (runId: string) => void;
  onSwitchToTemplates: () => void;
}

const PAGE_SIZE = 20;

export const WorkflowRunHistory: React.FC<Props> = ({ onSelectRun, onSwitchToTemplates }) => {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listRuns({ limit: PAGE_SIZE, offset: 0 });
      setRuns(data.runs);
      setTotal(data.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // ── Loading ──
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF', fontSize: 13 }}>
        加载运行记录...
      </div>
    );
  }

  // ── Error ──
  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <div style={{ fontSize: 13, color: '#DC2626', marginBottom: 12 }}>
          运行记录加载失败
        </div>
        <div style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 12 }}>{error}</div>
        <button onClick={loadRuns}
          style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 12, color: '#374151' }}>
          重新加载
        </button>
      </div>
    );
  }

  // ── Empty ──
  if (runs.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <div style={{ fontSize: 14, color: '#6B7280', marginBottom: 8 }}>
          暂无运行记录
        </div>
        <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 16 }}>
          从"工作流模板"中启动一个流程后，运行记录会显示在这里。
        </div>
        <button onClick={onSwitchToTemplates}
          style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #0F766E', background: '#F0FDFA', cursor: 'pointer', fontSize: 12, color: '#0F766E' }}>
          查看工作流模板
        </button>
      </div>
    );
  }

  // ── List ──
  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {runs.map(run => (
          <WorkflowRunCard key={run.runId} run={run} onClick={onSelectRun} />
        ))}
      </div>
      {total > PAGE_SIZE && (
        <div style={{ textAlign: 'center', padding: '12px 0 4px', fontSize: 11, color: '#9CA3AF' }}>
          当前显示 {runs.length} / {total}
        </div>
      )}
    </div>
  );
};
