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
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { ReloadOutlined } from '@ant-design/icons';
import { getHistory, getEventById } from '../../api/index';
import type { EventRecord, AnalyzeResult } from '../../types/index';
import { collabApi } from '../../api/collaborationApi';
import type { RunListItem as CollaborationRunListItem } from '../../api/collaborationApi';
import { createPlanFromAgent, listPlans, runPlan } from '../../api/planningApi';
import type { PlanListItem } from '../../types/planning';
import { listRuns } from '../../api/workflowApi';
import type { RunSummary } from '../../types/workflow';
import { RUN_STATUS_LABELS } from '../../types/workflow';
import { RelatedWorkflowRuns } from '../workflow/RelatedWorkflowRuns';
import { visualTokens } from '../../styles/visualTokens';
import { eventTitle, eventTypeLabel, isIncompleteEvent } from '../../utils/display';

const LIMIT = 50;
const { color, radius, shadow, font } = visualTokens;

const riskColor = (level: string): string => {
  switch (level) {
    case '重大风险': return '#7F1D1D';
    case '高风险': return '#DC2626';
    case '中风险': return '#D97706';
    case '低风险': return '#16A34A';
    default: return '#6B7280';
  }
};

const riskTagStyle = (level: string): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  minHeight: 20,
  padding: '1px 7px',
  borderRadius: 6,
  color: riskColor(level),
  background: !level ? '#F8FAFC' : ['重大风险', '高风险'].includes(level) ? '#FEF2F2' : level === '中风险' ? '#FFFBEB' : '#F0FDF4',
  border: `1px solid ${!level ? '#E2E8F0' : ['重大风险', '高风险'].includes(level) ? '#FECACA' : level === '中风险' ? '#FDE68A' : '#BBF7D0'}`,
  fontWeight: 700,
});

const statusTagStyle = (status: string): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  minHeight: 20,
  padding: '1px 7px',
  borderRadius: 6,
  color: isOpenStatus(status) ? '#B45309' : isClosedStatus(status) ? '#047857' : '#475569',
  background: isOpenStatus(status) ? '#FFFBEB' : isClosedStatus(status) ? '#ECFDF5' : '#F8FAFC',
  border: `1px solid ${isOpenStatus(status) ? '#FDE68A' : isClosedStatus(status) ? '#A7F3D0' : '#E2E8F0'}`,
  fontWeight: 600,
});

const thStyle: React.CSSProperties = {
  position: 'sticky',
  top: 0,
  zIndex: 1,
  padding: '7px 8px',
  fontWeight: 800,
  fontSize: 11,
  background: color.surfaceMuted,
  borderBottom: `1px solid ${color.border}`,
};

const tdStyle: React.CSSProperties = {
  padding: '6px 8px',
  borderBottom: `1px solid ${color.borderSubtle}`,
  verticalAlign: 'middle',
};

interface RoadRiskSummary {
  roadName: string;
  count: number;
  openCount: number;
  avgRisk: number;
  maxRisk: number;
}

function riskRank(level?: string | null): number {
  if (level === '重大风险') return 4;
  if (level === '高风险') return 3;
  if (level === '中风险') return 2;
  if (level === '低风险') return 1;
  return 0;
}

function isClosedStatus(status?: string | null): boolean {
  return ['closed', 'completed', 'done', '已闭环', '已关闭', '完成', '已完成'].includes(String(status || ''));
}

function isOpenStatus(status?: string | null): boolean {
  const s = String(status || '');
  return !isClosedStatus(s) && ['待派单', 'pending', 'unclosed', 'running', 'awaiting_approval', '处理中', '未闭环'].some(x => s.includes(x));
}

function statusUrgency(status?: string | null): number {
  if (isClosedStatus(status)) return 0;
  if (isOpenStatus(status)) return 2;
  return status ? 1 : 0;
}

function timestampMs(value?: string | null): number {
  if (!value) return Number.POSITIVE_INFINITY;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : Number.POSITIVE_INFINITY;
}

function comparePriority(a: EventRecord, b: EventRecord): number {
  const riskDelta = riskRank(b.riskLevel) - riskRank(a.riskLevel);
  if (riskDelta !== 0) return riskDelta;
  const scoreDelta = (b.riskScore ?? -1) - (a.riskScore ?? -1);
  if (scoreDelta !== 0) return scoreDelta;
  const statusDelta = statusUrgency(b.status) - statusUrgency(a.status);
  if (statusDelta !== 0) return statusDelta;
  return timestampMs(a.createdAt) - timestampMs(b.createdAt);
}

function durationHours(value?: string): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  if (!Number.isFinite(ms)) return null;
  return Math.max(0, Math.floor((Date.now() - ms) / 3600000));
}

function buildAttentionReasons(ev: FocusEvent, sameRoadCount: number): string[] {
  const reasons: string[] = [];
  if (ev.riskLevel) reasons.push(`${ev.riskLevel}事件`);
  if (ev.riskScore !== null) reasons.push(`风险评分 ${ev.riskScore}`);
  const hours = durationHours(ev.createdAt);
  if (hours !== null && hours >= 24) reasons.push(`已持续超过 ${Math.floor(hours / 24)} 天`);
  else if (hours !== null && hours >= 1) reasons.push(`已持续 ${hours} 小时`);
  if (isOpenStatus(ev.status)) reasons.push(`当前仍${ev.status}`);
  if (sameRoadCount > 1) reasons.push(`同一路段存在 ${sameRoadCount} 起事件`);
  return reasons.length > 0 ? reasons : ['按当前真实记录展示，暂无额外关注规则命中'];
}

function aggregateRoads(records: EventRecord[]): RoadRiskSummary[] {
  const buckets = new Map<string, { totalRisk: number; countedRisk: number; maxRisk: number; count: number; openCount: number }>();
  for (const r of records) {
    const roadName = r.roadName?.trim();
    if (!roadName) continue;
    const bucket = buckets.get(roadName) || { totalRisk: 0, countedRisk: 0, maxRisk: 0, count: 0, openCount: 0 };
    bucket.count += 1;
    if (isOpenStatus(r.status)) bucket.openCount += 1;
    if (typeof r.riskScore === 'number' && Number.isFinite(r.riskScore)) {
      bucket.totalRisk += r.riskScore;
      bucket.countedRisk += 1;
      bucket.maxRisk = Math.max(bucket.maxRisk, r.riskScore);
    }
    buckets.set(roadName, bucket);
  }
  return Array.from(buckets.entries())
    .map(([roadName, x]) => ({
      roadName,
      count: x.count,
      openCount: x.openCount,
      avgRisk: x.countedRisk > 0 ? Math.round((x.totalRisk / x.countedRisk) * 10) / 10 : 0,
      maxRisk: x.maxRisk,
    }))
    .sort((a, b) => b.maxRisk - a.maxRisk || b.count - a.count || b.avgRisk - a.avgRisk);
}

interface Props {
  focusEventId: string | null;
  focusRoadName: string | null;
  focusRisk: string | null;
  onClearFocus: () => void;
  onOpenRun?: (runId: string) => void;
  onOpenRoad?: (roadName: string) => void;
  onOpenPlan?: (planId: string) => void;
  onOpenCollaboration?: (sessionId: string) => void;
  onOpenKnowledge?: () => void;
  onSummaryChange?: (summary: { total: number | null; loaded: number; highRiskLoaded: number }) => void;
}

/** 聚焦事件归一化展示字段（EventRecord / AnalyzeResult 两种来源共用） */
interface FocusEvent {
  eventId: string;
  typeCn: string;
  roadName: string;
  riskLevel: string;
  riskScore: number | null;
  status: string;
  createdAt?: string;
}

/** 单查聚焦结果三态：checking | found | not_found | error */
type FocusState =
  | { kind: 'checking' }
  | { kind: 'found'; ev: FocusEvent }
  | { kind: 'not_found' }
  | { kind: 'error'; message: string };

type ActionBusy = 'analysis' | 'plan' | 'workflow' | null;

/** EventRecord → 聚焦展示字段 */
const fromRecord = (r: EventRecord): FocusEvent => ({
  eventId: r.eventId, typeCn: eventTypeLabel(r.eventTypeCn || r.eventType), roadName: r.roadName,
  riskLevel: r.riskLevel, riskScore: r.riskScore ?? null, status: r.status, createdAt: r.createdAt,
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
    typeCn: eventTypeLabel(pickText(top.eventTypeCn, top.eventType, standard.eventTypeCn, standard.eventType, fullStandard.eventTypeCn, fullStandard.eventType)),
    roadName: pickText(top.roadName, standard.roadName, fullStandard.roadName),
    riskLevel: pickText(top.riskLevel, fullResult.riskLevel),
    riskScore: pickNumber(top.riskScore, fullResult.riskScore),
    status: pickText(top.status, fullResult.status),
    createdAt: pickText(top.createdAt, fullResult.createdAt, top.analyzedAt, fullResult.analyzedAt),
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

export const RealEventsPanel: React.FC<Props> = ({ focusEventId, focusRoadName, focusRisk, onClearFocus, onOpenRun, onOpenRoad, onOpenPlan, onOpenCollaboration, onOpenKnowledge, onSummaryChange }) => {
  const [records, setRecords] = useState<EventRecord[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(focusEventId);
  const [collaborationRuns, setCollaborationRuns] = useState<CollaborationRunListItem[]>([]);
  const [collaborationTotal, setCollaborationTotal] = useState<number | null>(null);
  const [plans, setPlans] = useState<PlanListItem[]>([]);
  const [planTotal, setPlanTotal] = useState<number | null>(null);
  const [relatedRuns, setRelatedRuns] = useState<RunSummary[]>([]);
  const [relatedTotal, setRelatedTotal] = useState<number | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [relationReloadKey, setRelationReloadKey] = useState(0);
  const [actionBusy, setActionBusy] = useState<ActionBusy>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const relatedRequestSeqRef = useRef(0);
  const writeActionInFlightRef = useRef(false);

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
  const highRiskLoaded = useMemo(() => records.filter(r => ['高风险', '重大风险'].includes(r.riskLevel)).length, [records]);

  useEffect(() => {
    onSummaryChange?.({ total, loaded: records.length, highRiskLoaded });
  }, [highRiskLoaded, onSummaryChange, records.length, total]);

  const filtered = records.filter(r =>
    (!filterType || (r.eventTypeCn || r.eventType) === filterType) &&
    (!filterStatus || r.status === filterStatus) &&
    (!filterRoad || r.roadName === filterRoad) &&
    (!filterRisk || r.riskLevel === filterRisk),
  );
  const prioritized = useMemo(() => [...filtered].sort(comparePriority), [filtered]);
  const roadSummaries = useMemo(() => aggregateRoads(records), [records]);

  useEffect(() => {
    if (focusEventId) {
      setSelectedEventId(focusEventId);
      return;
    }
    if (prioritized.length > 0 && !prioritized.some(r => r.eventId === selectedEventId)) {
      setSelectedEventId(prioritized[0].eventId);
    }
  }, [prioritized, focusEventId, selectedEventId]);

  const hasFocus = Boolean(focusEventId || focusRoadName || focusRisk);
  const selectedRecord = prioritized.find(r => r.eventId === selectedEventId) || prioritized[0] || null;
  const selectedFocusEvent = focusEventId && focusState.kind === 'found' ? focusState.ev : null;
  const selectedEvent = focusEventId ? selectedFocusEvent : (selectedRecord ? fromRecord(selectedRecord) : null);
  const queueRecords = prioritized.slice(0, 12);
  const unclosedLoaded = records.filter(r => !isClosedStatus(r.status)).length;
  const selectedTitle = selectedEvent ? eventTitle({ roadName: selectedEvent.roadName, eventTypeCn: selectedEvent.typeCn }) : '选择事件查看详情';
  const selectedIncomplete = selectedEvent ? isIncompleteEvent({ roadName: selectedEvent.roadName, eventTypeCn: selectedEvent.typeCn }) : false;
  const selectedRoadEventCount = selectedEvent?.roadName ? records.filter(r => r.roadName === selectedEvent.roadName).length : 0;
  const attentionReasons = selectedEvent ? buildAttentionReasons(selectedEvent, selectedRoadEventCount) : [];

  useEffect(() => {
    const eventId = selectedEvent?.eventId;
    if (!eventId) {
      relatedRequestSeqRef.current += 1;
      setCollaborationRuns([]);
      setCollaborationTotal(null);
      setPlans([]);
      setPlanTotal(null);
      setRelatedRuns([]);
      setRelatedTotal(null);
      setRelatedError(null);
      setRelatedLoading(false);
      return;
    }
    const seq = ++relatedRequestSeqRef.current;
    setCollaborationRuns([]);
    setCollaborationTotal(null);
    setPlans([]);
    setPlanTotal(null);
    setRelatedRuns([]);
    setRelatedTotal(null);
    setRelatedError(null);
    setRelatedLoading(true);
    Promise.allSettled([
      collabApi.listEventRuns(eventId, 20, 0),
      listPlans({ eventId, pageSize: 20 }),
      listRuns({ event_id: eventId, limit: 50, offset: 0 }),
    ]).then(([collaborationResult, planResult, workflowResult]) => {
      if (seq !== relatedRequestSeqRef.current) return;
      const errors: string[] = [];
      if (collaborationResult.status === 'fulfilled') {
        setCollaborationRuns(collaborationResult.value.runs || []);
        setCollaborationTotal(typeof collaborationResult.value.total === 'number' ? collaborationResult.value.total : (collaborationResult.value.runs || []).length);
      } else {
        errors.push(`研判关系查询失败：${errorText(collaborationResult.reason)}`);
      }
      if (planResult.status === 'fulfilled') {
        setPlans(planResult.value.plans || []);
        setPlanTotal(typeof planResult.value.total === 'number' ? planResult.value.total : (planResult.value.plans || []).length);
      } else {
        errors.push(`方案关系查询失败：${errorText(planResult.reason)}`);
      }
      if (workflowResult.status === 'fulfilled') {
        setRelatedRuns(workflowResult.value.runs || []);
        setRelatedTotal(typeof workflowResult.value.total === 'number' ? workflowResult.value.total : (workflowResult.value.runs || []).length);
      } else {
        errors.push(`工作流关系查询失败：${errorText(workflowResult.reason)}`);
      }
      setRelatedError(errors.length > 0 ? errors.join('；') : null);
    }).finally(() => {
      if (seq === relatedRequestSeqRef.current) setRelatedLoading(false);
    });
  }, [relationReloadKey, selectedEvent?.eventId]);

  const selectStyle: React.CSSProperties = {
    padding: '5px 8px', borderRadius: 6, border: '1px solid #CBD5E1',
    background: '#FFF', fontSize: 12, color: '#334155', cursor: 'pointer',
  };

  const handleRoadSelect = useCallback((roadName: string) => {
    if (!roadName) return;
    if (onOpenRoad) onOpenRoad(roadName);
    else setFilterRoad(roadName);
  }, [onOpenRoad]);

  const refreshRelations = useCallback(() => setRelationReloadKey(k => k + 1), []);
  const latestCollaboration = useMemo(() => latestCollaborationRun(collaborationRuns), [collaborationRuns]);
  const latestPlan = useMemo(() => latestPlanItem(plans), [plans]);
  const latestRun = useMemo(() => latestWorkflowRun(relatedRuns), [relatedRuns]);

  useEffect(() => {
    setActionError(null);
  }, [selectedEvent?.eventId]);

  const handleStartAnalysis = useCallback(async () => {
    if (!selectedEvent) return;
    if (writeActionInFlightRef.current) return;
    writeActionInFlightRef.current = true;
    setActionBusy('analysis');
    setActionError(null);
    let streamError = '';
    try {
      await collabApi.streamCollaboration({
        eventId: selectedEvent.eventId,
        mode: 'collaboration',
        contextPolicy: 'fresh_event',
        content: `请基于真实交通事件「${selectedTitle}」开展协同研判，并输出可用于处置方案的结构化建议。`,
      }, {
        onError: err => { streamError = err; },
      });
      if (streamError) throw new Error(streamError);
      refreshRelations();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '研判启动失败');
    } finally {
      writeActionInFlightRef.current = false;
      setActionBusy(null);
    }
  }, [refreshRelations, selectedEvent, selectedTitle]);

  const handleCreatePlan = useCallback(async () => {
    if (!selectedEvent || !latestCollaboration) return;
    const runId = collaborationRunId(latestCollaboration);
    if (!runId) return;
    if (writeActionInFlightRef.current) return;
    writeActionInFlightRef.current = true;
    setActionBusy('plan');
    setActionError(null);
    try {
      await createPlanFromAgent({
        eventId: selectedEvent.eventId,
        sessionId: collaborationSessionId(latestCollaboration),
        collaborationRunId: runId,
        plannerMode: 'deterministic',
      });
      refreshRelations();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '方案生成失败');
    } finally {
      writeActionInFlightRef.current = false;
      setActionBusy(null);
    }
  }, [latestCollaboration, refreshRelations, selectedEvent]);

  const handleStartPlanWorkflow = useCallback(async () => {
    if (!selectedEvent || !latestPlan) return;
    if (writeActionInFlightRef.current) return;
    writeActionInFlightRef.current = true;
    setActionBusy('workflow');
    setActionError(null);
    const controller = new AbortController();
    let runCreated = false;
    let streamError = '';
    try {
      await runPlan(latestPlan.planId, {
        event: { eventId: selectedEvent.eventId },
        sessionId: latestCollaboration ? collaborationSessionId(latestCollaboration) : '',
        triggeredBy: 'traffic_realtime',
      }, {
        signal: controller.signal,
        onEvent: (eventType) => {
          if (eventType === 'run_created') {
            runCreated = true;
            refreshRelations();
            controller.abort();
          }
        },
        onError: err => { streamError = err; },
      });
      if (streamError && !runCreated) throw new Error(streamError);
      refreshRelations();
    } catch (err) {
      if (runCreated && err instanceof DOMException && err.name === 'AbortError') {
        refreshRelations();
        return;
      }
      setActionError(err instanceof Error ? err.message : '工作流启动失败');
    } finally {
      writeActionInFlightRef.current = false;
      setActionBusy(null);
    }
  }, [latestCollaboration, latestPlan, refreshRelations, selectedEvent]);

  return (
    <div style={{ background: color.surface, borderRadius: radius.md, border: `1px solid ${color.border}`, padding: 14, boxShadow: shadow.subtle }}>
      <style>{`
        .real-events-workbench {
          display: grid;
          grid-template-columns: minmax(280px, 0.9fr) minmax(320px, 1.1fr);
          gap: 12px;
        }
        @media (max-width: 980px) {
          .real-events-workbench { grid-template-columns: 1fr; }
        }
      `}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, gap: 10, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, color: color.text }}>实时态势</div>
          <div style={{ marginTop: 4, fontSize: 12, fontWeight: 400, color: color.textMuted }}>
            真实事件记录 · 当前显示 {filtered.length} / 已加载 {records.length} · 共 {total ?? '加载中'} 条 · 按风险、状态和持续时间排序
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {hasFocus && (
            <button onClick={onClearFocus}
              style={{ padding: '4px 10px', borderRadius: radius.sm, border: '1px solid #FECACA', background: '#FEF2F2', cursor: 'pointer', fontSize: 11, color: color.danger }}>
              清除聚焦
            </button>
          )}
          <button onClick={reload}
            style={{ padding: '5px 10px', borderRadius: radius.sm, border: `1px solid ${color.border}`, background: color.surface, cursor: 'pointer', fontSize: 12, color: '#334155', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <ReloadOutlined /> 刷新
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, marginBottom: 12 }}>
        <MiniMetric label="真实事件" value={total ?? '加载中'} hint={`已加载 ${records.length} 条`} />
        <MiniMetric label="高风险" value={highRiskLoaded} hint="高风险 / 重大风险" />
        <MiniMetric label="待处理" value={unclosedLoaded} hint="未闭环记录" />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12, padding: '8px 10px', background: color.surfaceMuted, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md }}>
        <span style={{ fontSize: 11, color: color.textMuted, fontWeight: 600 }}>筛选最近 50 条已加载记录</span>
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
          <span style={{ fontSize: 11, color: color.warning, fontWeight: 600 }}>已过滤：{filtered.length} / {records.length}</span>
        )}
      </div>

      {focusEventId && focusState.kind !== 'found' && (
        <div style={{ background: color.primarySoft, border: `1px solid ${color.primaryBorder}`, borderRadius: radius.md, padding: '9px 12px', marginBottom: 10, fontSize: 11 }}>
          {focusState.kind === 'checking' && <span style={{ color: color.textMuted }}>正在读取聚焦事件...</span>}
          {focusState.kind === 'not_found' && (
            <span style={{ color: color.danger }}>聚焦事件：未找到 / 已删除</span>
          )}
          {focusState.kind === 'error' && (
            <span style={{ color: color.danger }}>聚焦事件查询失败：{focusState.message}</span>
          )}
        </div>
      )}

      {loading ? <EmptyBlock text="正在加载真实事件..." />
      : error ? <EmptyBlock text={`真实事件加载失败：${error}`} action={<button onClick={reload} style={smallButtonStyle}>重试</button>} />
      : records.length === 0 ? <EmptyBlock text="暂无真实事件记录" />
      : (
        <>
          <div className="real-events-workbench">
            <section style={subPanelStyle}>
              <div style={{ ...subTitleStyle, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                <span>重点事件队列</span>
                <span style={{ fontSize: 11, color: color.textSubtle, fontWeight: 500 }}>确定性排序</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 420, overflowY: 'auto' }}>
                {queueRecords.length === 0 ? (
                  <EmptyBlock text="当前筛选条件下无匹配事件" compact />
                ) : queueRecords.map((r, index) => {
                  const active = selectedEvent?.eventId === r.eventId;
                  const title = eventTitle({ roadName: r.roadName, eventTypeCn: r.eventTypeCn, eventType: r.eventType });
                  const incomplete = isIncompleteEvent({ roadName: r.roadName, eventTypeCn: r.eventTypeCn, eventType: r.eventType });
                  const sameRoadCount = r.roadName ? records.filter(item => item.roadName === r.roadName).length : 0;
                  return (
                    <button key={r.eventId} onClick={() => setSelectedEventId(r.eventId)}
                      style={{ textAlign: 'left', padding: '10px 12px', borderRadius: radius.md, border: `1px solid ${active ? color.primaryBorder : color.borderSubtle}`, background: active ? color.primarySoft : color.surface, cursor: 'pointer', transition: 'background 160ms ease, border-color 160ms ease' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
                            <span style={{ flexShrink: 0, fontSize: 10, color: active ? color.primary : color.textSubtle, fontWeight: 700 }}>重点 {index + 1}</span>
                            <div style={{ fontSize: 13, fontWeight: 600, color: color.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</div>
                          </div>
                          <div style={{ marginTop: 3, fontSize: 11, color: color.textMuted }}>{r.roadName || '未记录路段'} · {timeAgo(r.createdAt)}</div>
                        </div>
                        <span style={riskTagStyle(r.riskLevel)}>{r.riskLevel || '未记录'}</span>
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, color: color.textSubtle, fontSize: 10 }}>
                        <span>{r.status || '未记录状态'}</span>
                        {sameRoadCount > 1 && <span>同路段 {sameRoadCount} 起</span>}
                        {incomplete && <span style={{ color: color.warning }}>信息不完整</span>}
                        <span style={{ marginLeft: 'auto', fontFamily: font.mono }}>事件编号 {r.eventId || '未记录'}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>

            <section style={subPanelStyle}>
              <div style={subTitleStyle}>选中事件详情</div>
              {selectedEvent ? (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', marginBottom: 10 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 17, fontWeight: 600, color: color.text, lineHeight: 1.35 }}>{selectedTitle}</div>
                      <div style={{ marginTop: 4, fontSize: 12, color: color.textMuted }}>
                        {selectedEvent.roadName || '未记录路段'} · {selectedEvent.createdAt ? new Date(selectedEvent.createdAt).toLocaleString() : '时间未记录'}
                      </div>
                    </div>
                    <span style={riskTagStyle(selectedEvent.riskLevel)}>{selectedEvent.riskLevel || '未记录'}</span>
                  </div>
                  {selectedIncomplete && (
                    <div style={{ marginBottom: 10, color: color.warning, fontSize: 12 }}>信息不完整：当前记录缺少可读路段或事件类型。</div>
                  )}
                  <AttentionReasons reasons={attentionReasons} />
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8, marginBottom: 10 }}>
                    <DetailItem label="事件类型" value={selectedEvent.typeCn || '未记录'} />
                    <DetailItem label="当前状态" value={selectedEvent.status || '未记录'} />
                    <DetailItem label="风险评分" value={selectedEvent.riskScore ?? '未记录'} />
                    <DetailItem label="持续时间" value={timeAgo(selectedEvent.createdAt)} />
                  </div>
                  <ResponseStagePanel
                    selectedEvent={selectedEvent}
                    collaborationRuns={collaborationRuns}
                    collaborationTotal={collaborationTotal}
                    plans={plans}
                    planTotal={planTotal}
                    relatedRuns={relatedRuns}
                    relatedTotal={relatedTotal}
                    loading={relatedLoading}
                    error={relatedError}
                    actionBusy={actionBusy}
                    actionError={actionError}
                    latestCollaboration={latestCollaboration}
                    latestPlan={latestPlan}
                    latestRun={latestRun}
                    onStartAnalysis={handleStartAnalysis}
                    onCreatePlan={handleCreatePlan}
                    onStartWorkflow={handleStartPlanWorkflow}
                    onOpenRun={onOpenRun}
                    onOpenPlan={onOpenPlan}
                    onOpenCollaboration={onOpenCollaboration}
                  />
                  <details style={{ marginBottom: 10, color: color.textSubtle, fontSize: 11 }}>
                    <summary style={{ cursor: 'pointer' }}>技术信息</summary>
                    <div style={{ marginTop: 5, fontFamily: font.mono, wordBreak: 'break-all' }}>事件编号 {selectedEvent.eventId || '未记录'}</div>
                  </details>
                  {onOpenRun ? (
                    <RelatedWorkflowRuns eventId={selectedEvent.eventId} onOpenRun={onOpenRun} />
                  ) : (
                    <div style={{ fontSize: 11, color: color.textSubtle }}>暂无相关工作流入口</div>
                  )}
                  <KnowledgePrompt onOpenKnowledge={onOpenKnowledge} />
                </div>
              ) : (
                <EmptyBlock text="选择事件查看详情" compact />
              )}
            </section>
          </div>

          <HighRiskRoadsPanel roads={roadSummaries.slice(0, 6)} onOpenRoad={handleRoadSelect} />

          <section style={{ ...subPanelStyle, marginTop: 12 }}>
            <div style={subTitleStyle}>真实事件表</div>
            <div style={{ overflowX: 'auto', border: `1px solid ${color.border}`, borderRadius: radius.md, maxHeight: 360 }}>
              <table style={{ width: '100%', minWidth: 760, borderCollapse: 'separate', borderSpacing: 0, fontSize: 12 }}>
                <thead>
                  <tr style={{ color: color.textMuted, textAlign: 'left', background: color.surfaceMuted }}>
                    <th style={thStyle}>事件</th>
                    <th style={thStyle}>路段</th>
                    <th style={thStyle}>风险</th>
                    <th style={thStyle}>状态</th>
                    <th style={thStyle}>记录时间</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(r => (
                    <tr key={r.eventId} onClick={() => setSelectedEventId(r.eventId)}
                      style={{ background: r.eventId === selectedEvent?.eventId ? color.primarySoft : color.surface, cursor: 'pointer' }}>
                      <td style={{ ...tdStyle }}>
                        <div style={{ color: color.text, fontWeight: 600 }}>{eventTitle({ roadName: r.roadName, eventTypeCn: r.eventTypeCn, eventType: r.eventType })}</div>
                        <div style={{ marginTop: 2, fontFamily: font.mono, fontSize: 10, color: color.textSubtle }}>事件编号 {r.eventId || '未记录'}</div>
                      </td>
                      <td style={{ ...tdStyle, color: '#374151' }}>{r.roadName || '未记录'}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <span style={riskTagStyle(r.riskLevel)}>{r.riskLevel || '未记录'}</span>
                        <span style={{ color: color.textSubtle, marginLeft: 4, fontVariantNumeric: 'tabular-nums' }}>{r.riskScore ?? '未记录'}</span>
                      </td>
                      <td style={tdStyle}><span style={statusTagStyle(r.status)}>{r.status || '未记录'}</span></td>
                      <td style={{ ...tdStyle, color: color.textMuted, fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>{r.createdAt ? new Date(r.createdAt).toLocaleString() : '未记录'}</td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ padding: '16px 8px', textAlign: 'center', color: color.textSubtle, fontSize: 12 }}>当前筛选条件下无匹配记录（筛选范围：最近 50 条已加载记录）</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
};

const subPanelStyle: React.CSSProperties = {
  background: color.surface,
  border: `1px solid ${color.borderSubtle}`,
  borderRadius: radius.md,
  padding: 12,
};

const subTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: color.text,
  marginBottom: 10,
};

const smallButtonStyle: React.CSSProperties = {
  cursor: 'pointer',
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  padding: '3px 10px',
  fontSize: 11,
  background: color.surface,
};

const AttentionReasons: React.FC<{ reasons: string[] }> = ({ reasons }) => (
  <div style={{ marginBottom: 10, background: color.surfaceMuted, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md, padding: '9px 10px' }}>
    <div style={{ fontSize: 12, fontWeight: 650, color: color.text, marginBottom: 6 }}>为什么需要关注</div>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {reasons.map(reason => (
        <span key={reason} style={{ fontSize: 11, color: color.textMuted, background: color.surface, border: `1px solid ${color.border}`, borderRadius: radius.sm, padding: '3px 7px' }}>
          {reason}
        </span>
      ))}
    </div>
  </div>
);

const ResponseStagePanel: React.FC<{
  selectedEvent: FocusEvent;
  collaborationRuns: CollaborationRunListItem[];
  collaborationTotal: number | null;
  plans: PlanListItem[];
  planTotal: number | null;
  relatedRuns: RunSummary[];
  relatedTotal: number | null;
  loading: boolean;
  error: string | null;
  actionBusy: ActionBusy;
  actionError: string | null;
  latestCollaboration: CollaborationRunListItem | null;
  latestPlan: PlanListItem | null;
  latestRun: RunSummary | null;
  onStartAnalysis: () => void;
  onCreatePlan: () => void;
  onStartWorkflow: () => void;
  onOpenRun?: (runId: string) => void;
  onOpenPlan?: (planId: string) => void;
  onOpenCollaboration?: (sessionId: string) => void;
}> = ({
  selectedEvent,
  collaborationRuns,
  collaborationTotal,
  plans,
  planTotal,
  relatedRuns,
  relatedTotal,
  loading,
  error,
  actionBusy,
  actionError,
  latestCollaboration,
  latestPlan,
  latestRun,
  onStartAnalysis,
  onCreatePlan,
  onStartWorkflow,
  onOpenRun,
  onOpenPlan,
  onOpenCollaboration,
}) => {
  const workflowTotal = relatedTotal ?? relatedRuns.length;
  const judgementTotal = collaborationTotal ?? collaborationRuns.length;
  const planCount = planTotal ?? plans.length;
  const sessionCount = new Set(collaborationRuns.map(r => collaborationSessionId(r)).filter(Boolean)).size;
  const latestCollaborationSessionId = latestCollaboration ? collaborationSessionId(latestCollaboration) : '';
  const judgementFailed = Boolean(error && collaborationTotal === null);
  const planFailed = Boolean(error && planTotal === null);
  const workflowFailed = Boolean(error && relatedTotal === null);
  const judgementStatus = loading ? '查询中' : judgementFailed ? '查询失败' : judgementTotal > 0
    ? `${judgementTotal} 条 · ${collaborationStatusLabel(latestCollaboration?.status)}`
    : '未开始';
  const planStatus = loading ? '查询中' : planFailed ? '查询失败' : planCount > 0
    ? `${planCount} 个 · ${latestPlan ? planVersionLabel(latestPlan) : '版本未记录'}`
    : '未关联';
  const workflowValue = loading ? '查询中' : workflowFailed ? '查询失败' : workflowTotal > 0
    ? `${workflowTotal} 条 · ${latestRun ? RUN_STATUS_LABELS[latestRun.status] || latestRun.status : '状态未记录'}`
    : '未开始';
  const closureStatus = isClosedStatus(selectedEvent.status)
    ? '事件已闭环'
    : latestRun?.status === 'completed'
      ? '执行完成，事件待闭环'
      : '待闭环';
  const primary = buildPrimaryAction({
    loading,
    actionBusy,
    latestCollaboration,
    latestPlan,
    latestRun,
    onStartAnalysis,
    onCreatePlan,
    onStartWorkflow,
    onOpenRun,
    onOpenPlan,
    onOpenCollaboration,
  });

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 650, color: color.text, marginBottom: 7 }}>处置闭环</div>
      <PrimaryAction action={primary} busy={actionBusy} />
      {actionError && <div style={{ margin: '6px 0 8px', fontSize: 11, color: color.danger }}>操作失败：{actionError}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(92px, 1fr))', gap: 6 }}>
        <StageCard label="事件" value={selectedEvent.status || '已记录'} active />
        <StageCard
          label="研判"
          value={judgementStatus}
          active={judgementTotal > 0}
          danger={judgementFailed}
          action={latestCollaborationSessionId && onOpenCollaboration ? <button onClick={() => onOpenCollaboration(latestCollaborationSessionId)} style={linkButtonStyle}>查看</button> : undefined}
        />
        <StageCard
          label="处置方案"
          value={planStatus}
          active={planCount > 0}
          danger={planFailed}
          action={latestPlan && onOpenPlan ? <button onClick={() => onOpenPlan(latestPlan.planId)} style={linkButtonStyle}>查看</button> : undefined}
        />
        <StageCard
          label="工作流"
          value={workflowValue}
          active={workflowTotal > 0}
          danger={workflowFailed}
          action={latestRun && onOpenRun ? <button onClick={() => onOpenRun(latestRun.runId)} style={linkButtonStyle}>查看</button> : undefined}
        />
        <StageCard label="知识依据" value="暂无持久化关系" />
        <StageCard label="闭环" value={closureStatus} active={isClosedStatus(selectedEvent.status) || latestRun?.status === 'completed'} />
      </div>
      {sessionCount > 0 ? (
        <div style={{ marginTop: 7, fontSize: 11, color: color.textMuted }}>相关会话：{sessionCount} 个，来自真实事件绑定研判记录。</div>
      ) : (
        <div style={{ marginTop: 7, fontSize: 11, color: color.textSubtle }}>相关会话/Agent：未关联。</div>
      )}
      {planTotal !== null && planTotal > plans.length && (
        <div style={{ marginTop: 4, fontSize: 11, color: color.textSubtle }}>当前显示 {plans.length} / 共 {planTotal} 个关联方案。</div>
      )}
      {relatedTotal !== null && relatedTotal > relatedRuns.length && (
        <div style={{ marginTop: 4, fontSize: 11, color: color.textSubtle }}>当前显示 {relatedRuns.length} / 共 {relatedTotal} 条关联工作流。</div>
      )}
      {error && <div style={{ marginTop: 5, fontSize: 11, color: color.danger }}>{error}</div>}
    </div>
  );
};

interface PrimaryActionState {
  label: string;
  hint: string;
  disabled?: boolean;
  onClick?: () => void;
}

const PrimaryAction: React.FC<{ action: PrimaryActionState; busy: ActionBusy }> = ({ action, busy }) => (
  <div style={{ marginBottom: 9, padding: '9px 10px', borderRadius: radius.md, border: `1px solid ${color.primaryBorder}`, background: color.primarySoft, display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 12, color: color.text, fontWeight: 650 }}>下一步</div>
      <div style={{ marginTop: 3, fontSize: 11, color: color.textMuted }}>{action.hint}</div>
    </div>
    <button
      onClick={action.onClick}
      disabled={action.disabled || !action.onClick || Boolean(busy)}
      style={{ border: `1px solid ${color.primary}`, background: color.primary, color: '#FFF', borderRadius: radius.sm, padding: '6px 12px', fontSize: 12, fontWeight: 650, cursor: action.disabled || busy ? 'not-allowed' : 'pointer', opacity: action.disabled || busy ? 0.58 : 1 }}
    >
      {busy ? '处理中...' : action.label}
    </button>
  </div>
);

const StageCard: React.FC<{ label: string; value: string; active?: boolean; danger?: boolean; action?: React.ReactNode }> = ({ label, value, active, danger, action }) => (
  <div style={{ minWidth: 0, background: active ? color.primarySoft : color.surfaceMuted, border: `1px solid ${danger ? '#FECACA' : active ? color.primaryBorder : color.borderSubtle}`, borderRadius: radius.sm, padding: '7px 8px' }}>
    <div style={{ fontSize: 10, color: color.textSubtle }}>{label}</div>
    <div style={{ marginTop: 3, fontSize: 11, color: danger ? color.danger : active ? color.primary : color.textMuted, fontWeight: 650, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={value}>
      {value}
    </div>
    {action && <div style={{ marginTop: 4 }}>{action}</div>}
  </div>
);

const KnowledgePrompt: React.FC<{ onOpenKnowledge?: () => void }> = ({ onOpenKnowledge }) => (
  <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: radius.md, border: `1px solid ${color.borderSubtle}`, background: color.surfaceMuted, fontSize: 11, color: color.textMuted, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
    <span>当前事件暂无已持久化知识依据关系；不会把临时检索当作已有证据。</span>
    {onOpenKnowledge && <button onClick={onOpenKnowledge} style={linkButtonStyle}>在知识库检索相关规则</button>}
  </div>
);

const HighRiskRoadsPanel: React.FC<{ roads: RoadRiskSummary[]; onOpenRoad: (roadName: string) => void }> = ({ roads, onOpenRoad }) => (
  <section style={{ ...subPanelStyle, marginTop: 12 }}>
    <div style={{ ...subTitleStyle, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
      <span>高风险路段</span>
      <span style={{ fontSize: 11, color: color.textSubtle, fontWeight: 500 }}>基于已加载真实事件聚合</span>
    </div>
    {roads.length === 0 ? (
      <EmptyBlock text="暂无可聚合路段" compact />
    ) : (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
        {roads.map((road, index) => (
          <button key={road.roadName} onClick={() => onOpenRoad(road.roadName)}
            style={{ textAlign: 'left', background: color.surface, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md, padding: '9px 10px', cursor: 'pointer' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <strong style={{ fontSize: 12, color: color.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{index + 1}. {road.roadName}</strong>
              <span style={{ fontSize: 11, color: riskColor(road.maxRisk >= 80 ? '重大风险' : road.maxRisk >= 60 ? '高风险' : '中风险'), fontWeight: 700 }}>{road.maxRisk}</span>
            </div>
            <div style={{ marginTop: 5, fontSize: 11, color: color.textMuted }}>
              {road.count} 起 · 未闭环 {road.openCount} · 平均风险 {road.avgRisk}
            </div>
          </button>
        ))}
      </div>
    )}
  </section>
);

const linkButtonStyle: React.CSSProperties = {
  border: 'none',
  background: 'transparent',
  color: color.primary,
  cursor: 'pointer',
  padding: 0,
  fontSize: 11,
  fontWeight: 650,
};

const MiniMetric: React.FC<{ label: string; value: string | number; hint: string }> = ({ label, value, hint }) => (
  <div style={{ background: color.surfaceMuted, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.md, padding: '9px 11px', minWidth: 0 }}>
    <div style={{ fontSize: 11, color: color.textMuted }}>{label}</div>
    <div style={{ marginTop: 3, fontSize: 18, color: color.text, fontWeight: 650, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    <div style={{ marginTop: 2, fontSize: 10, color: color.textSubtle }}>{hint}</div>
  </div>
);

const DetailItem: React.FC<{ label: string; value: string | number }> = ({ label, value }) => (
  <div style={{ background: color.surfaceMuted, border: `1px solid ${color.borderSubtle}`, borderRadius: radius.sm, padding: '8px 10px', minWidth: 0 }}>
    <div style={{ fontSize: 11, color: color.textMuted }}>{label}</div>
    <div style={{ marginTop: 3, fontSize: 13, color: color.text, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
  </div>
);

const EmptyBlock: React.FC<{ text: string; compact?: boolean; action?: React.ReactNode }> = ({ text, compact, action }) => (
  <div style={{ textAlign: 'center', padding: compact ? 14 : 28, color: color.textSubtle, fontSize: 12 }}>
    <div>{text}</div>
    {action && <div style={{ marginTop: 8 }}>{action}</div>}
  </div>
);

function timeAgo(value?: string): string {
  if (!value) return '时间未记录';
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return '时间未记录';
  const diffMs = Date.now() - time;
  if (diffMs < 0) return new Date(value).toLocaleString();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 60) return `已持续 ${Math.max(1, minutes)} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `已持续 ${hours} 小时`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours > 0 ? `已持续 ${days} 天 ${restHours} 小时` : `已持续 ${days} 天`;
}

function latestWorkflowRun(runs: RunSummary[]): RunSummary | null {
  if (runs.length === 0) return null;
  const runTime = (run: RunSummary) => {
    const ms = timestampMs(run.updatedAt || run.startedAt);
    return Number.isFinite(ms) ? ms : 0;
  };
  return [...runs].sort((a, b) =>
    activeStatusRank(b.status) - activeStatusRank(a.status) ||
    runTime(b) - runTime(a) ||
    b.runId.localeCompare(a.runId)
  )[0];
}

function latestCollaborationRun(runs: CollaborationRunListItem[]): CollaborationRunListItem | null {
  if (runs.length === 0) return null;
  return [...runs].sort((a, b) =>
    activeStatusRank(b.status) - activeStatusRank(a.status) ||
    timestampScore(b.updated_at || b.started_at) - timestampScore(a.updated_at || a.started_at) ||
    collaborationRunId(b).localeCompare(collaborationRunId(a))
  )[0];
}

function latestPlanItem(plans: PlanListItem[]): PlanListItem | null {
  if (plans.length === 0) return null;
  return [...plans].sort((a, b) =>
    activeStatusRank(b.latestExecutionStatus || '') - activeStatusRank(a.latestExecutionStatus || '') ||
    timestampScore(b.updatedAt || b.createdAt) - timestampScore(a.updatedAt || a.createdAt) ||
    b.planId.localeCompare(a.planId)
  )[0];
}

function timestampScore(value?: string | null): number {
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

function activeStatusRank(status?: string | null): number {
  const s = String(status || '');
  if (s === 'awaiting_approval') return 6;
  if (['running', 'paused', 'pending'].includes(s)) return 5;
  if (s === 'completed') return 4;
  if (['failed', 'rejected', 'cancelled'].includes(s)) return 2;
  return s ? 3 : 0;
}

function collaborationRunId(run: CollaborationRunListItem): string {
  return String(run.run_id || '');
}

function collaborationSessionId(run: CollaborationRunListItem): string {
  return String(run.session_id || '');
}

function collaborationStatusLabel(status?: string | null): string {
  const labels: Record<string, string> = {
    pending: '待启动',
    running: '研判中',
    routing: '路由中',
    arbitrating: '仲裁中',
    fusing: '融合中',
    completed: '已完成',
    partial_success: '部分完成',
    failed: '失败',
    interrupted: '已中断',
  };
  const key = String(status || '');
  return labels[key] || key || '状态未记录';
}

function planVersionLabel(plan: PlanListItem): string {
  if (plan.replanCount > 0) return `第 ${plan.replanCount} 次调整`;
  if (plan.latestVersion <= 1) return '初始方案';
  return `方案版本 ${plan.latestVersion}`;
}

function isCollaborationReady(run: CollaborationRunListItem | null): boolean {
  return ['completed', 'partial_success'].includes(String(run?.status || ''));
}

function errorText(value: unknown): string {
  return value instanceof Error ? value.message : String(value || '查询失败');
}

function buildPrimaryAction(args: {
  loading: boolean;
  actionBusy: ActionBusy;
  latestCollaboration: CollaborationRunListItem | null;
  latestPlan: PlanListItem | null;
  latestRun: RunSummary | null;
  onStartAnalysis: () => void;
  onCreatePlan: () => void;
  onStartWorkflow: () => void;
  onOpenRun?: (runId: string) => void;
  onOpenPlan?: (planId: string) => void;
  onOpenCollaboration?: (sessionId: string) => void;
}): PrimaryActionState {
  if (args.loading) {
    return { label: '查询中', hint: '正在读取该事件的研判、方案和工作流关系。', disabled: true };
  }
  if (args.latestRun) {
    const label = args.latestRun.status === 'awaiting_approval'
      ? '处理审批'
      : args.latestRun.status === 'completed'
        ? '查看执行结果'
        : ['failed', 'rejected', 'cancelled'].includes(args.latestRun.status)
          ? '查看失败详情'
          : '查看执行进展';
    return {
      label,
      hint: `已存在事件绑定工作流：${RUN_STATUS_LABELS[args.latestRun.status] || args.latestRun.status}。`,
      onClick: args.onOpenRun ? () => args.onOpenRun?.(args.latestRun!.runId) : undefined,
      disabled: !args.onOpenRun,
    };
  }
  if (args.latestPlan) {
    return {
      label: args.actionBusy === 'workflow' ? '启动执行中' : '启动执行',
      hint: `已有关联处置方案（${planVersionLabel(args.latestPlan)}），可启动事件绑定工作流。`,
      onClick: args.onStartWorkflow,
    };
  }
  if (args.latestCollaboration) {
    if (String(args.latestCollaboration.status || '') === 'failed') {
      return {
        label: args.actionBusy === 'analysis' ? '重新研判中' : '重新研判',
        hint: '上次研判失败，可基于同一真实事件重新启动研判。',
        onClick: args.onStartAnalysis,
      };
    }
    if (!isCollaborationReady(args.latestCollaboration)) {
      const sessionId = collaborationSessionId(args.latestCollaboration);
      return {
        label: '查看研判',
        hint: `研判已开始：${collaborationStatusLabel(args.latestCollaboration.status)}。`,
        onClick: sessionId && args.onOpenCollaboration ? () => args.onOpenCollaboration?.(sessionId) : undefined,
        disabled: !sessionId || !args.onOpenCollaboration,
      };
    }
    return {
      label: args.actionBusy === 'plan' ? '生成方案中' : '生成处置方案',
      hint: '将使用真实事件绑定的结构化 Agent 研判生成方案。',
      onClick: args.onCreatePlan,
    };
  }
  return {
    label: args.actionBusy === 'analysis' ? '研判中' : '开始研判',
    hint: '从当前真实事件启动 Agent 协同研判，并持久化事件关系。',
    onClick: args.onStartAnalysis,
  };
}
