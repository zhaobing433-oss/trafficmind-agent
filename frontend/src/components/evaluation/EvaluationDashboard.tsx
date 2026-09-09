/** Phase 14 Round 3 — Evaluation Dashboard */
import React, { useEffect, useState } from 'react';
import { listReports, getReport, compareReports, getReportSummary } from '../../api/evaluationApi';
import type { EvalReportSummary, EvalReportFull, EvalCaseDetail, ReportCompare, EvalSummary } from '../../types/evaluation';

/** 三态徽章：PASS / FAIL / UNKNOWN / 未记录（后端 summary 为 authority，不前端推算） */
const STATUS_STYLE: Record<string, { bg: string; fg: string }> = {
  PASS: { bg: '#ECFDF5', fg: '#059669' },
  FAIL: { bg: '#FEF2F2', fg: '#DC2626' },
  UNKNOWN: { bg: '#F3F4F6', fg: '#6B7280' },
};

const statusBadge = (s: string | null | undefined): React.ReactNode => {
  const v = s || '';
  if (!v) return <span style={{ fontSize: 10, color: '#9CA3AF' }}>未记录</span>;
  const st = STATUS_STYLE[v] || STATUS_STYLE.UNKNOWN;
  return <span style={{ fontSize: 10, padding: '1px 8px', borderRadius: 8, background: st.bg, color: st.fg, fontWeight: 600 }}>{v}</span>;
};

const displayCount = (val: number | null | undefined): string => (
  val === null || val === undefined ? '—' : String(val)
);

const fmtGateValue = (val: number | null | undefined): string => {
  if (val === null || val === undefined) return '—';
  return Number.isFinite(val) ? String(val) : '—';
};

export const EvaluationDashboard: React.FC = () => {
  const [reports, setReports] = useState<EvalReportSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [report, setReport] = useState<EvalReportFull | null>(null);
  // Phase20 R2：产品级总览 — GET /evaluation/reports/{id}/summary
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [detailCase, setDetailCase] = useState<EvalCaseDetail | null>(null);
  const [compare, setCompare] = useState<ReportCompare | null>(null);
  const [compareTarget, setCompareTarget] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [reportCount, setReportCount] = useState(0);

  // Step 1: Load reports, auto-select latest if no URL param
  useEffect(() => {
    listReports(50).then(items => {
      setReports(items);
      setReportCount(items.length);
      if (!items.length) return;

      const params = new URLSearchParams(window.location.search);
      const urlId = params.get('report');
      const initial = items.find(r => r.reportId === urlId)?.reportId ?? items[0].reportId;

      setSelectedId(initial);
      const url = new URL(window.location.href);
      url.searchParams.set('report', initial);
      window.history.replaceState({}, '', url.toString());
    }).catch(e => setError(e.message));
  }, []);

  // Step 2: Load report detail when selectedId changes
  useEffect(() => {
    if (!selectedId) return;
    getReport(selectedId).then(setReport).catch(() => setError('加载报告失败'));
    // Phase20 R2：summary 单独加载，失败不阻塞 full report（case/detail 仍可用）
    setSummary(null); setSummaryError(null);
    getReportSummary(selectedId)
      .then(setSummary)
      .catch(e => setSummaryError(e instanceof Error ? e.message : 'summary 加载失败'));
    setDetailCase(null);
    setCompare(null);
  }, [selectedId]);

  const persistId = (id: string) => {
    setSelectedId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('report', id);
    window.history.replaceState({}, '', url.toString());
  };

  const m = report?.metrics;
  const gate = report?.regressionGate;
  const cases = report?.caseResults ?? [];
  const filtered = filter === 'all' ? cases : cases.filter(c => !c.passed);
  const CLASS_LABELS: Record<string,string> = { A:'Evaluator Bug', B:'Dataset Label Bug', C:'Production Capability Gap' };

  function classifyCase(c: EvalCaseDetail): string {
    const cls = c.diagnostics?.classification as Record<string,unknown>|undefined;
    if (cls?.type) {
      const t = String(cls.type);
      if (t === 'production_capability_gap') return 'C';
      if (t === 'dataset_label_bug') return 'B';
      if (t === 'evaluator_bug') return 'A';
      return t;
    }
    return '';  // historical / unclassified
  }

  function classificationReason(c: EvalCaseDetail): string {
    const cls = c.diagnostics?.classification as Record<string,unknown>|undefined;
    return String(cls?.reason ?? '');
  }

  function parseAssertion(a: string): { category: string; detail: string } {
    const parts = a.split(':', 2);
    return { category: parts[0] ?? '', detail: parts.slice(1).join(':') || a };
  }

  // Map gate metric keys → EvalMetrics field names
  const GATE_METRIC_MAP: Record<string,string> = {
    overall: 'overallScore', overallScore: 'overallScore',
    eventFieldAccuracy: 'eventFieldAccuracy', requiredAgentRecall: 'requiredAgentRecall',
    conflictF1: 'conflictF1', safetyPolicyPassRate: 'safetyPolicyPassRate',
    workflowInvariantPassRate: 'workflowInvariantPassRate', outputStructurePassRate: 'outputStructurePassRate',
  };
  const GATE_DISPLAY: Record<string,string> = {
    overall: '总体得分', overallScore: '总体得分',
    eventFieldAccuracy: '事件字段准确率', requiredAgentRecall: '必需Agent召回率',
    conflictF1: '冲突检测F1', safetyPolicyPassRate: '安全策略通过率',
    workflowInvariantPassRate: '工作流约束通过率', outputStructurePassRate: '输出结构通过率',
  };
  const GATE_COUNT = Object.keys(gate?.thresholds ?? {}).length;
  const isLegacyGate = GATE_COUNT > 0 && GATE_COUNT < 7;

  const fmtMetric = (val: number | undefined | null): string => {
    if (val === undefined || val === null) return '—';
    return `${(val * 100).toFixed(1)}%`;
  };
  const summaryGates = Array.isArray(summary?.gates) ? summary.gates : [];

  return (
    <div style={{ fontSize: 12 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: '#111827', marginBottom: 12 }}>评测中心</h2>
      {error && <div style={{ background:'#FEF2F2',color:'#DC2626',padding:'8px 12px',borderRadius:8,marginBottom:8 }}>{error}<button onClick={()=>setError(null)} style={{ marginLeft:8,background:'none',border:'none',color:'#DC2626',cursor:'pointer' }}>✕</button></div>}

      {/* Report selector */}
      <div style={{ display:'flex',gap:8,alignItems:'center',marginBottom:12,flexWrap:'wrap' }}>
        <select value={selectedId} onChange={e => persistId(e.target.value)} style={{ padding:'4px 8px',borderRadius:6,border:'1px solid #D1D5DB',fontSize:12 }}>
          <option value="">选择评测报告...</option>
          {reports.map(r => (<option key={r.reportId} value={r.reportId}>{r.reportId.slice(-15)} — {r.datasetVersion || '未记录'} — {fmtMetric(r.overallScore)} — {r.passedCases}/{r.totalCases}</option>))}
        </select>
        {reportCount > 0 && <span style={{ color:'#9CA3AF',fontSize:11 }}>显示最近{reportCount}份</span>}
      </div>

      {report && m ? (
        <>
          {/* Phase20 R2：产品级总览（summary 为 authority；full report 继续用于 case/detail） */}
          <div style={{ background:'#FFF',borderRadius:8,border:'1px solid #E5E7EB',padding:'10px 12px',marginBottom:8 }}>
            <div style={{ display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6 }}>
              <div style={{ fontWeight:600,fontSize:12 }}>产品级总览</div>
              <span style={{ fontSize:9,color:'#9CA3AF' }}>GET /evaluation/reports/{'{id}'}/summary</span>
            </div>
            {summaryError ? (
              <div style={{ fontSize:11,color:'#DC2626' }}>summary 加载失败：{summaryError}</div>
            ) : !summary ? (
              <div style={{ fontSize:11,color:'#9CA3AF' }}>正在加载 summary…</div>
            ) : (
              <>
                <div style={{ display:'flex',gap:12,flexWrap:'wrap',alignItems:'center',fontSize:11,marginBottom:6 }}>
                  <span><span style={{ color:'#9CA3AF' }}>总体：</span>{statusBadge(summary.overallStatus)}</span>
                  <span><span style={{ color:'#9CA3AF' }}>指标：</span>{statusBadge(summary.metricsStatus)}</span>
                  <span><span style={{ color:'#9CA3AF' }}>门槛：</span>{statusBadge(summary.gateStatus)}</span>
                  <span style={{ color:'#374151' }}>
                    用例 {displayCount(summary.totalCases)} 个 · 通过 {displayCount(summary.passedCases)} · 失败 {displayCount(summary.failedCases)}
                    <span> · 总体得分 {fmtMetric(summary.overallScore)}</span>
                  </span>
                </div>
                {summaryGates.length > 0 && (
                  <div style={{ display:'flex',gap:8,flexWrap:'wrap',fontSize:10,marginBottom:4 }}>
                    {summaryGates.map(g => (
                      <span key={g.gateId} style={{ background:'#F9FAFB',borderRadius:6,padding:'2px 8px',color:'#374151' }}>
                        {g.gateId} {statusBadge(g.status)} <span style={{ color:'#9CA3AF' }}>{fmtGateValue(g.actual)} / 阈值 {fmtGateValue(g.threshold)}</span>
                      </span>
                    ))}
                  </div>
                )}
                <div style={{ display:'flex',gap:12,flexWrap:'wrap',fontSize:10,color:'#6B7280' }}>
                  <span>数据集：{summary.datasetVersion || '未记录'}</span>
                  <span>provider：{summary.provider || '未记录'}</span>
                  <span>model：{summary.model || '未记录'}</span>
                  <span>commit：{summary.commitSha || '未记录'}</span>
                  <span>生成时间：{summary.generatedAt || '未记录'}</span>
                </div>
              </>
            )}
          </div>

          {/* Metric cards */}
          <div style={{ display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(140px,1fr))',gap:8,marginBottom:12 }}>
              {[
                {l:'Overall',v:`${(m.overallScore*100).toFixed(1)}%`,c:summary?.overallStatus==='PASS'?'#0F766E':summary?.overallStatus==='FAIL'?'#EF4444':'#6B7280'},
                {l:'Gate',v:summary?(summary.gateStatus || '未记录'):'未记录',c:summary?.gateStatus==='PASS'?'#0F766E':summary?.gateStatus==='FAIL'?'#EF4444':'#6B7280'},
              {l:'Passed',v:`${m.passedCases}/${m.totalCases}`},
              {l:'Event',v:`${(m.eventFieldAccuracy*100).toFixed(0)}%`},
              {l:'Recall',v:`${(m.requiredAgentRecall*100).toFixed(1)}%`},
              {l:'Safety',v:`${(m.safetyPolicyPassRate*100).toFixed(0)}%`},
              {l:'Conflict F1',v:`${(m.conflictF1*100).toFixed(0)}%`},
              {l:'Workflow',v:`${(m.workflowInvariantPassRate*100).toFixed(0)}%`},
            ].map(mc => (
              <div key={mc.l} style={{ background:'#FFF',borderRadius:8,border:'1px solid #E5E7EB',padding:'8px 12px',textAlign:'center' }}>
                <div style={{ fontSize:10,color:'#9CA3AF' }}>{mc.l}</div>
                <div style={{ fontSize:18,fontWeight:700,color:mc.c||'#111827' }}>{mc.v}</div>
              </div>
            ))}
          </div>

          {/* Regression Gate */}
          <details open style={{ background:'#FFF',borderRadius:8,border:'1px solid #E5E7EB',padding:'8px 12px',marginBottom:8 }}>
            <summary style={{ fontWeight:600,cursor:'pointer' }}>
              Regression Gate {gate?.passed ? '✅' : '❌'}
              {isLegacyGate && <span style={{ fontSize:10,color:'#F59E0B',fontWeight:400,marginLeft:8 }}>历史评测规则 · 门槛可能与当前版本不同</span>}
            </summary>
            <div style={{ marginTop:4 }}>
              {gate && Object.entries(gate.thresholds).map(([k,th]) => {
                const metricKey = GATE_METRIC_MAP[k] ?? k;
                const v = (m as unknown as Record<string,number>)[metricKey];
                const fail = gate.failures.some(f => f.gate === k);
                const display = GATE_DISPLAY[k] ?? k;
                const hardGate = ['safetyPolicyPassRate','workflowInvariantPassRate'].includes(k);
                return <div key={k} style={{ display:'flex',justifyContent:'space-between',padding:'2px 0',fontSize:11,color:fail?'#EF4444':'#374151' }}>
                  <span>{display}{hardGate?' 🔒':''}<span style={{ fontSize:9,color:'#9CA3AF',marginLeft:4 }}>{k}</span></span>
                  <span style={{ fontWeight:600 }}>{fmtMetric(v)} / {(th*100).toFixed(0)}% {(th===1?'(必须)':'')} {fail?'❌':'✅'}</span>
                </div>;
              })}
            </div>
          </details>

          {/* Case filter */}
          <div style={{ display:'flex',gap:6,marginBottom:8 }}>
            {['all','fail'].map(f => <button key={f} onClick={()=>setFilter(f)} style={{ padding:'3px 10px',borderRadius:10,border:'1px solid #E5E7EB',background:filter===f?'#F0FDFA':'#FFF',cursor:'pointer',fontSize:11 }}>{f==='all'?`全部 (${cases.length})`:`失败 (${cases.filter(c=>!c.passed).length})`}</button>)}
            {selectedId && <button onClick={async()=>{const ids=reports.map(r=>r.reportId);const i=ids.indexOf(selectedId);if(i>0){setCompareTarget(ids[i-1]);try{setCompare(await compareReports(ids[i-1],selectedId))}catch{}}} } style={{ padding:'3px 10px',borderRadius:10,border:'1px solid #E5E7EB',background:'#FFF',cursor:'pointer',fontSize:11,marginLeft:'auto' }}>对比</button>}
          </div>

          {/* Case table */}
          <div style={{ background:'#FFF',borderRadius:8,border:'1px solid #E5E7EB',overflowX:'auto' }}>
            <div style={{ display:'grid',gridTemplateColumns:'60px 1fr 80px 60px 120px',gap:4,padding:'4px 8px',background:'#F9FAFB',fontSize:10,fontWeight:600,color:'#6B7280',minWidth:560 }}>
              <span>ID</span><span>名称</span><span>评分</span><span>状态</span><span>分类</span>
            </div>
            {filtered.map(c => (
              <div key={c.caseId} onClick={()=>setDetailCase(detailCase?.caseId===c.caseId?null:c)} style={{ display:'grid',gridTemplateColumns:'60px 1fr 80px 60px 120px',gap:4,padding:'4px 8px',borderBottom:'1px solid #F3F4F6',cursor:'pointer',background:detailCase?.caseId===c.caseId?'#F0FDFA':'#FFF',fontSize:11,minWidth:560 }}>
                <span style={{ fontWeight:600 }}>{c.caseId}</span><span>{c.name}</span>
                <span style={{ color:c.passed?'#0F766E':'#EF4444' }}>{(c.scores.overall*100).toFixed(0)}%</span>
                <span>{c.passed?'✅':'❌'}</span>
                <span style={{ color:'#6B7280' }}>{CLASS_LABELS[classifyCase(c)] ?? (c.diagnostics?.classification ? String(c.diagnostics.classification) : '—')}</span>
              </div>
            ))}
            {filtered.length===0 && <div style={{ padding:16,textAlign:'center',color:'#9CA3AF',fontSize:11 }}>无匹配case</div>}
          </div>

          {/* Case detail */}
          {detailCase && (() => {
            const cls = classifyCase(detailCase);
            const reason = classificationReason(detailCase);
            const routingDiag = detailCase.diagnostics?.routing as Record<string,string[]>|undefined;
            return (
            <div style={{ background:'#FFF',borderRadius:8,border:'1px solid #E5E7EB',padding:10,marginTop:8 }}>
              <div style={{ fontWeight:600,marginBottom:4,display:'flex',alignItems:'center',gap:8 }}>
                <span style={{ color:detailCase.passed?'#0F766E':'#EF4444' }}>{detailCase.passed?'✅':'❌'}</span>
                {detailCase.caseId} — {detailCase.name}
                {cls ? <span style={{ fontSize:10,background:'#FEF3C7',color:'#92400E',padding:'2px 6px',borderRadius:10 }}>{CLASS_LABELS[cls] ?? cls}</span>
                     : <span style={{ fontSize:10,color:'#9CA3AF' }}>未分类（历史报告）</span>}
              </div>

              {/* Routing diagnostics */}
              {routingDiag && (
                <div style={{ marginBottom:8,background:'#F9FAFB',borderRadius:6,padding:'6px 8px',fontSize:11 }}>
                  <div style={{ fontWeight:600,marginBottom:4 }}>路由诊断</div>
                  <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:4 }}>
                    <div><span style={{ color:'#9CA3AF' }}>必需 Agent:</span> {(routingDiag.requiredAgents??[]).join('、') || '—'}</div>
                    <div><span style={{ color:'#9CA3AF' }}>实际 Agent:</span> {(routingDiag.actualAgents??[]).join('、') || '—'}</div>
                    <div><span style={{ color:'#EF4444' }}>缺失:</span> {(routingDiag.missingAgents??[]).join('、') || '—'}</div>
                    <div><span style={{ color:'#6B7280' }}>额外:</span> {(routingDiag.extraAgents??[]).join('、') || '—'}</div>
                  </div>
                </div>
              )}

              {/* Scores */}
              <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'2px 12px',fontSize:11 }}>
                {Object.entries(detailCase.scores).filter(([k])=>k!=='overall').map(([k,v])=> <div key={k} style={{ display:'flex',justifyContent:'space-between' }}><span style={{ color:'#9CA3AF' }}>{k}</span><span>{(Number(v)*100).toFixed(1)}%</span></div> )}
              </div>

              {/* Failed assertions */}
              {detailCase.failedAssertions.length>0 && (
                <div style={{ marginTop:8 }}>
                  <div style={{ fontSize:10,color:'#DC2626',fontWeight:600,marginBottom:4 }}>失败断言</div>
                  {detailCase.failedAssertions.map((a,i) => {
                    const pa = parseAssertion(String(a));
                    const isSystemErr = String(a).includes('SYSTEM_ERROR');
                    return (
                    <div key={i} style={{ fontSize:10,color:'#991B1B',padding:'3px 0',borderBottom:'1px solid #FEE2E2' }}>
                      <span style={{ fontWeight:600 }}>{pa.category}:</span> {isSystemErr ? '系统执行异常' : pa.detail}
                    </div>
                  );})}
                </div>
              )}

              {/* Classification */}
              {reason && <div style={{ marginTop:6,fontSize:10,color:'#6B7280' }}>分类依据: {reason}</div>}
            </div>
          );})()}

          {/* Compare */}
          {compare && (
            <div style={{ background:'#FFF',borderRadius:8,border:'1px solid #E5E7EB',padding:10,marginTop:8 }}>
              <div style={{ fontWeight:600,marginBottom:4 }}>对比: {compare.baseReportId.slice(-12)} → {compare.targetReportId.slice(-12)}</div>
              {!compare.datasetVersionMatch && <div style={{ color:'#F59E0B',fontSize:10,marginBottom:4 }}>⚠ 数据集版本不同 — 指标变化可能包含 dataset 变化影响</div>}
              {compare.metricsDelta.map(d => <div key={d.metric} style={{ display:'flex',justifyContent:'space-between',fontSize:11,padding:'1px 0',color:d.status==='regressed'?'#EF4444':d.status==='improved'?'#0F766E':'#374151' }}>
                <span>{d.metric}</span><span>{d.status==='improved'?'↑':d.status==='regressed'?'↓':'→'} {d.percentagePoints>0?'+':''}{d.percentagePoints.toFixed(1)}pp</span>
              </div>)}
            </div>
          )}
        </>
      ) : (
        <div style={{ padding:32,textAlign:'center',color:'#9CA3AF',fontSize:13 }}>{reports.length === 0 ? '暂无评测报告' : '请选择评测报告查看结果'}</div>
      )}
    </div>
  );
};
