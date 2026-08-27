/**
 * RealEventsPanel — Phase 20 Round 1
 *
 * 真实事件面板：直接消费 GET /history（event_records 表），
 * 与上方模拟路网（仿真数据）在视觉上明确区分。
 * 空字段显示「未知 / 未记录」，绝不渲染损坏的空 UI。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { getHistory } from '../../api/index';
import type { EventRecord } from '../../types/index';

const LIMIT = 50;

const riskColor = (level: string): string => {
  switch (level) {
    case '重大风险': return '#7F1D1D';
    case '高风险': return '#DC2626';
    case '中风险': return '#D97706';
    case '低风险': return '#16A34A';
    default: return '#6B7280';
  }
};

export const RealEventsPanel: React.FC = () => {
  const [records, setRecords] = useState<EventRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    getHistory(LIMIT)
      .then(r => { if (!cancelled) { setRecords(r.records); setTotal(r.total); } })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : '加载失败'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reloadKey]);

  const reload = useCallback(() => setReloadKey(k => k + 1), []);

  return (
    <div style={{ marginTop: 12, background: '#FFF', borderRadius: 12, border: '1px solid #E5E7EB', padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#111827', display: 'flex', alignItems: 'center', gap: 8 }}>
          真实事件记录（数据库）
          <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 8, background: '#F0FDFA', color: '#0F766E', border: '1px solid #99F6E4' }}>真实数据</span>
          <span style={{ fontSize: 11, fontWeight: 400, color: '#9CA3AF' }}>来源 GET /history · 共 {total} 条</span>
        </div>
        <button onClick={reload}
          style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 11, color: '#6B7280' }}>
          ⟳ 刷新
        </button>
      </div>

      {loading ? <div style={{ textAlign: 'center', padding: 24, color: '#9CA3AF', fontSize: 12 }}>加载真实事件...</div>
      : error ? <div style={{ textAlign: 'center', padding: 24, color: '#DC2626', fontSize: 12 }}>真实事件加载失败：{error} <button onClick={reload} style={{ cursor: 'pointer', border: '1px solid #E5E7EB', borderRadius: 4, padding: '2px 8px', fontSize: 11 }}>重试</button></div>
      : records.length === 0 ? <div style={{ textAlign: 'center', padding: 24, color: '#9CA3AF', fontSize: 12 }}>暂无真实事件记录</div>
      : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', textAlign: 'left' }}>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>事件ID</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>类型</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>路段</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>风险</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>状态</th>
                <th style={{ padding: '6px 8px', fontWeight: 600 }}>记录时间</th>
              </tr>
            </thead>
            <tbody>
              {records.map(r => (
                <tr key={r.eventId} style={{ borderBottom: '1px solid #F3F4F6' }}>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 11, color: '#374151' }}>{r.eventId || '未知'}</td>
                  <td style={{ padding: '6px 8px', color: '#111827' }}>{r.eventTypeCn || r.eventType || '未知'}</td>
                  <td style={{ padding: '6px 8px', color: '#374151' }}>{r.roadName || '未记录'}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ color: riskColor(r.riskLevel) }}>{r.riskLevel || '未记录'}</span>
                    <span style={{ color: '#9CA3AF', marginLeft: 4 }}>{r.riskScore ?? '未记录'}</span>
                  </td>
                  <td style={{ padding: '6px 8px', color: '#374151' }}>{r.status || '未记录'}</td>
                  <td style={{ padding: '6px 8px', color: '#6B7280', fontSize: 11 }}>{r.createdAt ? new Date(r.createdAt).toLocaleString() : '未记录'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
