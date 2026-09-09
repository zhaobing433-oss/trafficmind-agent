import { useEffect, useState } from 'react';
import type { GroundingPresentation, GroundingRow } from '../../types/judgment';
import { provenanceLabel, record, text } from '../../utils/judgment';
import './judgment.css';

const statuses = { READY: '已记录', EMPTY: '未匹配', UNRESOLVED: '待确认', UNAVAILABLE: '未能获取', ERROR: '获取失败', NOT_RECORDED: '未记录' };

interface PublicHistoryDetail {
  sourceLabel: string;
  summary: string;
  metadata: string[];
  sourceUri: string;
}

function HistoryEvidenceRow({ row }: { row: GroundingRow }) {
  const [detail, setDetail] = useState<PublicHistoryDetail | null>(null);
  useEffect(() => {
    if (!row.eventId) return;
    const controller = new AbortController();
    void fetch(`/api/event/${encodeURIComponent(row.eventId)}`, { signal: controller.signal })
      .then(response => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
      .then(payload => {
        const top = record(payload), full = record(top.fullResult);
        const standard = record(top.rawEvent), fullStandard = record(full.standardEvent);
        const provenance = [standard.provenance, fullStandard.provenance, full.sourceProvenance, top.provenance]
          .map(record).find(value => text(value.sourceType)) || {};
        if (text(provenance.sourceType) !== 'real_public_reported_incident') {
          setDetail({ sourceLabel: provenanceLabel({ provenance }), summary: row.summary, metadata: row.metadata, sourceUri: '' });
          return;
        }
        const incident = [standard.publicIncident, fullStandard.publicIncident, full.publicIncident]
          .map(record).find(value => Object.keys(value).length > 0) || {};
        const occurredAt = text(incident.occurredAt);
        const sourceTier = text(provenance.sourceTier);
        setDetail({
          sourceLabel: '公开历史事件',
          summary: text(incident.locationText) || row.summary,
          metadata: [
            occurredAt ? `事件时间：${occurredAt}` : '事件时间未记录',
            text(provenance.sourceAuthority) ? `来源机构：${text(provenance.sourceAuthority)}` : '来源机构未记录',
            text(provenance.sourceTitle) ? `来源标题：${text(provenance.sourceTitle)}` : '来源标题未记录',
            sourceTier ? `来源级别：Tier ${sourceTier} · ${text(provenance.sourceDocumentType) || '公开资料'}` : '来源级别未记录',
          ],
          sourceUri: /^https:\/\//.test(text(provenance.sourceUri)) ? text(provenance.sourceUri) : '',
        });
      })
      .catch(error => { if (error?.name !== 'AbortError') setDetail(null); });
    return () => controller.abort();
  }, [row.eventId]);
  const shown = detail || { sourceLabel: row.sourceLabel, summary: row.summary, metadata: row.metadata, sourceUri: '' };
  return <details className="judgment-evidence-row">
    <summary><span className="judgment-row-title">{row.title}</span><span className="judgment-source">{shown.sourceLabel}</span></summary>
    {shown.summary && <p>{shown.summary}</p>}
    <ul className="judgment-muted">{shown.metadata.map((value, index) => <li key={index}>{value}</li>)}</ul>
    {shown.sourceUri && <a className="judgment-link" href={shown.sourceUri} target="_blank" rel="noopener noreferrer">查看公开来源</a>}
  </details>;
}

function CaseEvidenceRow({ row }: { row: GroundingRow }) {
  const [detail, setDetail] = useState<{ sourceLabel: string; metadata: string[] } | null>(null);
  useEffect(() => {
    if (!row.caseId) return;
    const controller = new AbortController();
    void fetch(`/api/case-memory/${encodeURIComponent(row.caseId)}`, { signal: controller.signal })
      .then(response => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
      .then(payload => {
        const value = record(payload), provenance = record(value.provenance);
        const reality = text(provenance.caseReality) || text(value.sourceType);
        const outcome = record(record(value.workflowOutcome).businessOutcome);
        const realityNote = reality === 'public_incident_replay_system_closure'
          ? '公开事件事实 · TrafficMind 系统验证回放，不是历史真实处置'
          : reality === 'synthetic_event_system_closure'
            ? '合成事件 · TrafficMind 系统闭环验证'
            : '案例现实类型未记录';
        setDetail({
          sourceLabel: provenanceLabel(value),
          metadata: [
            ...row.metadata.filter(item => !item.startsWith('实际交通处置效果：')),
            realityNote,
            text(outcome.status) === 'unknown_without_external_evidence'
              ? '实际交通处置效果：未记录' : '实际交通处置效果：来源未说明',
          ],
        });
      })
      .catch(error => { if (error?.name !== 'AbortError') setDetail(null); });
    return () => controller.abort();
  }, [row.caseId]);
  const shown = detail || { sourceLabel: row.sourceLabel, metadata: row.metadata };
  return <details className="judgment-evidence-row">
    <summary><span className="judgment-row-title">{row.title}</span>{row.outcome && <span className={`judgment-outcome${row.outcome === '已驳回' ? ' is-rejected' : ''}`}>{row.outcome}</span>}<span className="judgment-source">{shown.sourceLabel}</span></summary>
    {row.summary && <p>{row.summary}</p>}
    <ul className="judgment-muted">{shown.metadata.map((value, index) => <li key={index}>{value}</li>)}</ul>
  </details>;
}

export default function GroundingEvidencePanel({ grounding, onOpenKnowledge, loading = false }: {
  grounding?: GroundingPresentation; onOpenKnowledge?: (documentId: string) => void; loading?: boolean;
}) {
  return <section className="judgment-grounding" aria-label="本次研判背景与引用">
    <h3>本次研判背景与引用</h3>
    {loading ? <p className="judgment-muted">正在载入本次研判快照...</p> : !grounding?.recorded ? <p className="judgment-muted">{grounding?.invalid
      ? '本次研判上下文快照无法读取'
      : '该研判未记录分析时的上下文快照'}</p> : <>
      <p className="judgment-muted">本次研判时的上下文 · {grounding.assembledAt || '快照时间未记录'}</p>
      <div className="judgment-audit">
        <span>本次可用背景引用 {grounding.availableRefCount} 条</span>
        <span>角色输入引用 {grounding.inputRefCount} 条</span>
        <span>输出记录中的引用 {grounding.outputRefCount} 条</span>
        {grounding.auditRecorded && <span>已保存融合审计摘要</span>}
      </div>
      <p className="judgment-muted">输出引用包含系统附加的背景来源；模型实际使用情况未单独记录。</p>
      {grounding.outputRefLabels.length > 0 && <details className="judgment-output-refs"><summary>输出引用明细</summary>
        <ul>{grounding.outputRefLabels.map((label, i) => <li key={i}>{label}</li>)}</ul>
      </details>}
      {grounding.blocks.map(block => <section key={block.kind} className="judgment-block" data-grounding={block.kind}>
        <div className="judgment-block-heading"><h4>{block.title}</h4><span className={`judgment-source status-${block.status}`}>{statuses[block.status]}</span></div>
        {block.message && <p className="judgment-muted">{block.message}</p>}
        {block.status === 'READY' && block.metadata.length > 0 && <p className="judgment-muted">{block.metadata.join(' · ')}</p>}
        {block.status === 'READY' && block.rows.length === 0 && <p className="judgment-muted">快照未保留明细</p>}
        {block.rows.map((row, i) => block.kind === 'history' ? <HistoryEvidenceRow key={row.eventId || i} row={row} />
          : block.kind === 'case' ? <CaseEvidenceRow key={row.caseId || i} row={row} /> : <details key={i} className="judgment-evidence-row">
          <summary><span className="judgment-row-title">{row.title}</span>{row.outcome && <span className={`judgment-outcome${row.outcome === '已驳回' ? ' is-rejected' : ''}`}>{row.outcome}</span>}<span className="judgment-source">{row.sourceLabel}</span></summary>
          {row.summary && <p>{row.summary}</p>}
          <ul className="judgment-muted">{row.metadata.map((value, n) => <li key={n}>{value}</li>)}</ul>
          {row.documentId && onOpenKnowledge && <button className="judgment-link" onClick={() => onOpenKnowledge(row.documentId!)}>查看当前知识详情</button>}
        </details>)}
      </section>)}
    </>}
  </section>;
}
