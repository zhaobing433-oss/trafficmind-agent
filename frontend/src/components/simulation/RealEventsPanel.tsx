/**
 * RealEventsPanel — Phase 20 Round 2
 *
 * 真实事件面板：直接消费 GET /history（event_records 表），
 * 与上方模拟路网（仿真数据）在视觉上明确区分。
 *
 * 前端筛选（eventType / status / roadName / riskLevel）只作用于
 * 「最近 50 条已加载记录」，并持续显示该范围说明。
 *
 * focusEventId 深链：若聚焦事件不在已加载 50 条内，用
 * GET /event/{eventId} 单查聚焦（真实持久化 ID 为 authority）；
 * 404 → 显示「未找到 / 已删除」，绝不伪造。
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { getHistory, getEventById } from '../../api/index';
import type { EventRecord, AnalyzeResult } from '../../types/index';

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

interface Props {
  focusEventId: string | null;
  focusRoadName: string | null;
  focusRisk: string | null;
  onClearFocus: () => void;
}

/** 聚焦事件归一化展示字段（EventRecord / AnalyzeResult 两种来源共用） */
interface FocusEvent {
  eventId: string;
  typeCn: string;
  roadName: string;
  riskLevel: string;
  riskScore: number | null;
  status: string;
}

/** 单查聚焦结果三态：checking | found | not_found | error */
type FocusState =
  | { kind: 'checking' }
  | { kind: 'found'; ev: FocusEvent }
  | { kind: 'not_found' }
  | { kind: 'error'; message: string };

/** EventRecord → 聚焦展示字段 */
const fromRecord = (r: EventRecord): FocusEvent => ({
  eventId: r.eventId, typeCn: r.eventTypeCn || r.eventType, roadName: r.roadName,
  riskLevel: r.riskLevel, riskScore: r.riskScore ?? null, status: r.status,
});

type EventDetailResponse = Partial<AnalyzeResult> & Partial<EventRecord> & {
  fullResult?: Partial<AnalyzeResult> | null;
};

/** /event/{id} → 聚焦展示字段：top-level 优先，其次 standardEvent，最后 fullResult.standardEvent */
const fromAnalyze = (a: EventDetailResponse): FocusEvent => {
  const top = a as Record<string, unknown>;
  const standard = asObject(top.standardEvent);
  const fullResult = asObject(top.fullResult);
  const fullStandard = asObject(fullResult.standardEvent);

  return {
    eventId: pickText(top.eventId, standard.eventId, fullResult.eventId, fullStandard.eventId),
    typeCn: pickText(top.eventTypeCn, top.eventType, standard.eventTypeCn, standard.eventType, fullStandard.eventTypeCn, fullStandard.eventType),
    roadName: pickText(top.roadName, standard.roadName, fullStandard.roadName),
    riskLevel: pickText(top.riskLevel, fullResult.riskLevel),
    riskScore: pickNumber(top.riskScore, fullResult.riskScore),
    status: pickText(top.status, fullResult.status),
  };
};

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function pickText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function pickNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return null;
}

export const RealEventsPanel: React.FC<Props> = ({ focusEventId, focusRoadName, focusRisk, onClearFocus }) => {
  const [records, setRecords] = useState<EventRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // 前端筛选条件（只作用于已加载记录）
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterRoad, setFilterRoad] = useState('');
  const [filterRisk, setFilterRisk] = useState('');

  // 事件聚焦：不在已加载 50 条内时单查 GET /event/{eventId}
  const [focusState, setFocusState] = useState<FocusState>({ kind: 'checking' });

  // focusRoadName / focusRisk 深链 → 同步为筛选条件
  useEffect(() => {
    setFilterRoad(focusRoadName || '');
  }, [focusRoadName]);
  useEffect(() => {
    setFilterRisk(focusRisk || '');
  }, [focusRisk]);

  // 事件聚焦：优先命中已加载记录，否则单查（404 → 未找到/已删除）
  useEffect(() => {
    if (!focusEventId) { setFocusState({ kind: 'checking' }); return; }
    const hit = records.find(r => r.eventId === focusEventId);
    if (hit) {
      setFocusState({ kind: 'found', ev: fromRecord(hit) });
      return;
    }
    let cancelled = false;
    setFocusState({ kind: 'checking' });
    getEventById(focusEventId)
      .then(rec => { if (!cancelled) setFocusState({ kind: 'found', ev: fromAnalyze(rec) }); })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : '加载失败';
        // 404 → 未找到/已删除；其它错误 → 查询失败
        setFocusState(/404|不存在|not found/i.test(msg) ? { kind: 'not_found' } : { kind: 'error', message: msg });
      });
    return () => { cancelled = true; };
  }, [focusEventId, records]);

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

  // 筛选选项：从已加载记录中提取去重（不请求后端）
  const typeOptions = useMemo(() => [...new Set(records.map(r => r.eventTypeCn || r.eventType).filter(Boolean))].sort(), [records]);
  const statusOptions = useMemo(() => [...new Set(records.map(r => r.status).filter(Boolean))].sort(), [records]);
  const roadOptions = useMemo(() => [...new Set(records.map(r => r.roadName).filter(Boolean))].sort(), [records]);
  const riskOptions = useMemo(() => [...new Set(records.map(r => r.riskLevel).filter(Boolean))].sort(), [records]);

  const filtered = records.filter(r =>
    (!filterType || (r.eventTypeCn || r.eventType) === filterType) &&
    (!filterStatus || r.status === filterStatus) &&
    (!filterRoad || r.roadName === filterRoad) &&
    (!filterRisk || r.riskLevel === filterRisk),
  );

  const hasFocus = Boolean(focusEventId || focusRoadName || focusRisk);

  const selectStyle: React.CSSProperties = {
    padding: '2px 6px', borderRadius: 6, border: '1px solid #E5E7EB',
    background: '#FFF', fontSize: 11, color: '#374151', cursor: 'pointer',
  };

  return (
    <div style={{ marginTop: 12, background: '#FFF', borderRadius: 8, border: '1px solid #E5E7EB', padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#111827', display: 'flex', alignItems: 'center', gap: 8 }}>
          真实事件记录（数据库）
          <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 8, background: '#F0FDFA', color: '#0F766E', border: '1px solid #99F6E4' }}>真实数据</span>
          <span style={{ fontSize: 11, fontWeight: 400, color: '#9CA3AF' }}>来源 GET /history · 共 {total} 条</span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {hasFocus && (
            <button onClick={onClearFocus}
              style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #FECACA', background: '#FEF2F2', cursor: 'pointer', fontSize: 11, color: '#DC2626' }}>
              清除聚焦
            </button>
          )}
          <button onClick={reload}
            style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #E5E7EB', background: '#FFF', cursor: 'pointer', fontSize: 11, color: '#6B7280' }}>
            ⟳ 刷新
          </button>
        </div>
      </div>

      {/* 筛选行（前端过滤已加载记录） */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 10, color: '#9CA3AF' }}>筛选范围：最近 50 条已加载记录</span>
        <select value={filterType} onChange={e => setFilterType(e.target.value)} style={selectStyle}>
          <option value="">全部类型</option>
          {typeOptions.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={selectStyle}>
          <option value="">全部状态</option>
          {statusOptions.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filterRoad} onChange={e => setFilterRoad(e.target.value)} style={selectStyle}>
          <option value="">全部路段</option>
          {roadOptions.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={filterRisk} onChange={e => setFilterRisk(e.target.value)} style={selectStyle}>
          <option value="">全部风险</option>
          {riskOptions.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        {filtered.length !== records.length && (
          <span style={{ fontSize: 10, color: '#D97706' }}>已过滤：显示 {filtered.length} / {records.length} 条</span>
        )}
      </div>

      {/* 事件聚焦深链（?eventId=） */}
      {focusEventId && (
        <div style={{ background: '#EFF6FF', border: '1px solid #BFDBFE', borderRadius: 8, padding: '8px 12px', marginBottom: 8, fontSize: 11 }}>
          {focusState.kind === 'checking' && <span style={{ color: '#6B7280' }}>正在聚焦事件 {focusEventId} …</span>}
          {focusState.kind === 'not_found' && (
            <span style={{ color: '#DC2626' }}>聚焦事件 {focusEventId}：未找到 / 已删除</span>
          )}
          {focusState.kind === 'error' && (
            <span style={{ color: '#DC2626' }}>聚焦事件查询失败：{focusState.message}</span>
          )}
          {focusState.kind === 'found' && (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <strong style={{ color: '#111827' }}>聚焦事件</strong>
              <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#374151' }}>{focusEventId}</span>
              <span style={{ color: '#111827' }}>{focusState.ev.typeCn || '未知类型'}</span>
              <span style={{ color: '#374151' }}>{focusState.ev.roadName || '未记录'}</span>
              <span style={{ color: riskColor(focusState.ev.riskLevel) }}>{focusState.ev.riskLevel || '未记录'}</span>
              <span style={{ color: '#9CA3AF' }}>{focusState.ev.riskScore ?? '未记录'}</span>
              <span style={{ color: '#374151' }}>{focusState.ev.status || '未记录'}</span>
            </div>
          )}
        </div>
      )}

      {loading ? <div style={{ textAlign: 'center', padding: 24, color: '#9CA3AF', fontSize: 12 }}>正在加载真实事件...</div>
      : error ? <div style={{ textAlign: 'center', padding: 24, color: '#DC2626', fontSize: 12 }}>真实事件加载失败：{error} <button onClick={reload} style={{ cursor: 'pointer', border: '1px solid #E5E7EB', borderRadius: 4, padding: '2px 8px', fontSize: 11 }}>重试</button></div>
      : records.length === 0 ? <div style={{ textAlign: 'center', padding: 24, color: '#9CA3AF', fontSize: 12 }}>暂无真实事件记录</div>
      : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', minWidth: 720, borderCollapse: 'collapse', fontSize: 12 }}>
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
              {filtered.map(r => (
                <tr key={r.eventId} style={{ borderBottom: '1px solid #F3F4F6', background: r.eventId === focusEventId ? '#EFF6FF' : undefined }}>
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
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: '16px 8px', textAlign: 'center', color: '#9CA3AF', fontSize: 12 }}>当前筛选条件下无匹配记录（筛选范围：最近 50 条已加载记录）</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
