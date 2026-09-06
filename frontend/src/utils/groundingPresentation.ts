import { caseOutcome, judgmentTitle, provenanceLabel, record, records, strings, text } from './judgment';
import type { GroundingBlock, GroundingBlockStatus, GroundingPresentation } from '../types/judgment';

const numberText = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? String(value) : '未记录';
const dateText = (value: unknown) => text(value) || '未记录';
const blockNames = { regional: '区域信息', history: '历史事件', knowledge: '规则知识', case: '历史处置参考' };
const statusOf = (value: unknown): GroundingBlockStatus => ['READY', 'EMPTY', 'UNAVAILABLE', 'UNRESOLVED', 'ERROR'].includes(text(value)) ? text(value) as GroundingBlockStatus : 'NOT_RECORDED';
const refKey = (value: unknown): string => {
  if (typeof value === 'string') return value;
  const r = record(value);
  return text(r.evidenceId) || text(r.caseId) || text(r.bindingId) || text(r.documentId) || (text(r.type) === 'historical_traffic' ? 'history:' + text(r.asOf) : '');
};

export function groundingPresentation(raw: unknown, rawTasks: unknown, finalDecision: unknown): GroundingPresentation {
  const snapshot = record(raw);
  const recorded = Object.keys(snapshot).length > 0;
  const invalid = Boolean(raw && !recorded && (typeof raw !== 'object' ? text(raw).replace(/\s/g, '') !== '{}' : Array.isArray(raw)));
  const makeBlock = (kind: GroundingBlock['kind'], value: unknown): GroundingBlock => {
    const status = statusOf(record(value).status);
    const empty = kind === 'regional' ? '本次研判未记录区域信息' : `本次研判未检索到相关${blockNames[kind]}`;
    const unavailable = kind === 'regional' ? '本次研判未能获取区域上下文' : `本次研判未能获取${blockNames[kind]}上下文`;
    const message = status === 'EMPTY' ? empty : status === 'UNRESOLVED' ? '位置尚未确认'
      : status === 'NOT_RECORDED' ? '本次研判未记录此类上下文' : status === 'UNAVAILABLE' || status === 'ERROR' ? unavailable : '';
    return { kind, title: blockNames[kind], status, message, metadata: [], rows: [] };
  };
  const regional = record(snapshot.regionalContext), history = record(snapshot.historicalContext);
  const knowledge = record(snapshot.knowledgeContext), cases = record(snapshot.caseMemoryContext);
  const blocks = [makeBlock('regional', regional), makeBlock('history', history), makeBlock('knowledge', knowledge), makeBlock('case', cases)];
  const location = record(regional.location), region = record(regional.region), window = record(history.window);
  if (blocks[0].status === 'READY') {
    blocks[0].rows = [{ title: text(location.intersectionName) || text(location.roadName) || '位置名称未记录',
      summary: text(region.name) || '区域名称未记录', sourceLabel: provenanceLabel(region),
      metadata: [text(location.locationGranularity) === 'intersection' ? '已解析到路口' : text(location.locationGranularity) === 'road' ? '已解析到道路' : '位置精度未记录',
        '关联道路：' + (records(regional.connectedRoads).map(x => text(x.name)).filter(Boolean).join('、') || '未记录'),
        '周边场所：' + (records(regional.nearbyPois).map(x => text(x.name)).filter(Boolean).join('、') || '未记录')] }];
  }
  blocks[1].metadata = ['统计截止：' + dateText(window.asOf || record(history.provenance).asOf),
    '时间窗口：' + dateText(window.start) + ' 至 ' + dateText(window.end)];
  if (strings(record(history.provenance).notes).includes('strict_past_by_event_created_at')) blocks[1].metadata.push('仅包含该事件创建时间之前的记录');
  if (blocks[1].status === 'READY') {
    const refs = records(history.recentEventRefs);
    blocks[1].metadata.push('匹配 ' + numberText(history.eventCount) + ' 起 · 快照保留 ' + refs.length + ' 条明细');
    blocks[1].rows = refs.map(x => ({ title: judgmentTitle(x), summary: text(x.roadName) || '历史位置未记录',
      metadata: [text(x.riskLevel) || '风险未记录', text(x.status) || '状态未记录', dateText(x.createdAt)],
      sourceLabel: provenanceLabel(x.provenance ? x : history) }));
  }
  if (blocks[2].status === 'READY') blocks[2].rows = records(knowledge.evidence).map(x => ({
    title: text(x.title) || '规则标题未记录', summary: text(x.excerpt), documentId: text(x.documentId) || undefined,
    metadata: [text(x.authorityLevel) ? '来源级别：' + text(x.authorityLevel) : '来源级别未记录',
      '适用范围：' + (({ global: '通用', region: '区域', road: '道路', intersection: '路口' } as Record<string, string>)[text(x.groundingScope)] || '未记录'),
      '有效期：' + dateText(x.effectiveFrom) + ' 至 ' + dateText(x.effectiveTo), text(x.sourceUri)].filter(Boolean),
    sourceLabel: provenanceLabel(x.provenance || x.sourceType ? x : knowledge),
  }));
  if (blocks[3].status === 'READY') blocks[3].rows = records(cases.cases).map(x => ({
    title: judgmentTitle(x), summary: text(x.generatedSummary), outcome: caseOutcome(x.finalStatus),
    metadata: ['位置：' + (text(x.roadName) || text(x.intersectionName) || '快照未记录名称'),
      '审批结果：' + (({ rejected: '已驳回', approved: '已批准' } as Record<string, string>)[text(x.approvalStatus)] || '未单独记录'),
      dateText(x.completedAt), ...records(x.lessonRefs).map(y => text(y.summary)).filter(Boolean)],
    sourceLabel: provenanceLabel(x.provenance || x.sourceType ? x : cases),
  }));

  const available = Array.isArray(snapshot.groundingRefs) ? snapshot.groundingRefs : [];
  const availableKeys = new Set(available.map(refKey).filter(Boolean));
  const outputs = records(rawTasks).map(t => record(t.output_snapshot ?? t.outputSnapshot));
  const outputRefs = outputs.flatMap(o => {
    const refs = o.evidence_refs ?? o.evidenceRefs;
    return Array.isArray(refs) ? refs : [];
  });
  const keys = [...new Set(outputRefs.map(refKey).filter(Boolean))];
  const inputFacts = new Set(records(rawTasks).flatMap(t => strings(record(t.input_snapshot ?? t.inputSnapshot).groundingFacts)));
  const inputRefs = records(rawTasks).flatMap(t => {
    const refs = record(t.input_snapshot ?? t.inputSnapshot).groundingEvidenceRefs;
    return Array.isArray(refs) ? refs : [];
  });
  const labels = new Map<string, string>();
  for (const x of records(knowledge.evidence)) labels.set(refKey(x), text(x.title) || '规则知识');
  for (const x of records(cases.cases)) labels.set(refKey(x), judgmentTitle(x) + ' · ' + caseOutcome(x.finalStatus));
  return { recorded, invalid, assembledAt: text(snapshot.assembledAt), blocks,
    availableRefCount: availableKeys.size, outputRefCount: keys.length,
    outputRefLabels: keys.map(key => labels.get(key) || (availableKeys.has(key) ? '背景来源引用' : '来源名称未记录')),
    // The current executor adds grounding refs to outputs; this cannot prove model use.
    usageUnverified: true, auditRecorded: Object.keys(record(record(finalDecision).groundingAudit)).length > 0,
    inputFactCount: inputFacts.size, inputRefCount: new Set(inputRefs.map(refKey).filter(Boolean)).size };
}
