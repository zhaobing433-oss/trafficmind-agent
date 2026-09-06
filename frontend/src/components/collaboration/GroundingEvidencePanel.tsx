import type { GroundingPresentation } from '../../types/judgment';
import './judgment.css';

const statuses = { READY: '已记录', EMPTY: '未匹配', UNRESOLVED: '待确认', UNAVAILABLE: '未能获取', ERROR: '获取失败', NOT_RECORDED: '未记录' };

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
        {block.rows.map((row, i) => <details key={i} className="judgment-evidence-row">
          <summary><span className="judgment-row-title">{row.title}</span>{row.outcome && <span className={`judgment-outcome${row.outcome === '已驳回' ? ' is-rejected' : ''}`}>{row.outcome}</span>}<span className="judgment-source">{row.sourceLabel}</span></summary>
          {row.summary && <p>{row.summary}</p>}
          <ul className="judgment-muted">{row.metadata.map((value, n) => <li key={n}>{value}</li>)}</ul>
          {row.documentId && onOpenKnowledge && <button className="judgment-link" onClick={() => onOpenKnowledge(row.documentId!)}>查看当前知识详情</button>}
        </details>)}
      </section>)}
    </>}
  </section>;
}
