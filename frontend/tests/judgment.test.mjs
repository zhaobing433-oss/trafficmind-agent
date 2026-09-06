import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { loadTs } from './loadTs.mjs';

const { groupRecentJudgments, selectJudgmentRun, provenanceLabel } = loadTs(new URL('../src/utils/judgment.ts', import.meta.url));
const { groundingPresentation } = loadTs(new URL('../src/utils/groundingPresentation.ts', import.meta.url));
const { loadJudgmentSelection, validateJudgmentDetail } = loadTs(new URL('../src/utils/judgmentQuery.ts', import.meta.url));
const Panel = loadTs(new URL('../src/components/collaboration/GroundingEvidencePanel.tsx', import.meta.url)).default;
const Recent = loadTs(new URL('../src/components/collaboration/RecentJudgments.tsx', import.meta.url)).default;
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const run = (id, sid, eid, date, status = 'completed') => ({ run_id: id, session_id: sid, normalized_event: { eventId: eid, roadName: '文泽路', eventType: 'accident' }, started_at: date, status });
const session = (id, runs, extra = {}) => ({ session: { id, title: '文泽路交通事故', mode: 'collaboration' }, runs, ...extra });
const present = (snapshot, tasks = []) => groundingPresentation(snapshot, tasks, { groundingAudit: { status: 'FULL' } });
const html = grounding => renderToStaticMarkup(React.createElement(Panel, { grounding, onOpenKnowledge: () => {} }));
const recentHtml = judgments => renderToStaticMarkup(React.createElement(Recent, { judgments, judgmentsLoading: false, judgmentsError: null, onOpenJudgment: () => {}, onRecentClick: () => {} }));
const context = () => ({ assembledAt: '2026-09-06T10:00:00Z',
  regionalContext: { status: 'READY', region: { name: '钱塘', verificationStatus: 'real_public_verified' }, location: { roadName: '文泽路', locationGranularity: 'road' }, connectedRoads: [], nearbyPois: [] },
  historicalContext: { status: 'READY', eventCount: 1, window: { asOf: '2026-09-01', start: '2026-08-01', end: '2026-09-01' }, provenance: { sourceType: 'synthetic_validation', notes: ['strict_past_by_event_created_at'] }, recentEventRefs: [{ eventId: 'history', eventType: 'accident', riskLevel: '高风险', status: '待派单', createdAt: '2026-08-30' }] },
  knowledgeContext: { status: 'EMPTY', evidence: [] },
  caseMemoryContext: { status: 'READY', provenance: { sourceType: 'synthetic_event_system_closure' }, cases: [{ caseId: 'case-ref', eventType: 'accident', finalStatus: 'rejected', generatedSummary: '保留人工驳回记录' }] },
  groundingRefs: [{ bindingId: 'b' }, { type: 'historical_traffic', asOf: '2026-09-01' }, { caseId: 'case-ref' }],
});

test('persisted event grouping is one row across sessions, legacy is never guessed', () => {
  const result = groupRecentJudgments([
    session('s1', [run('r1', 's1', 'A', '2026-09-01')]), session('s2', [run('r2', 's2', 'A', '2026-09-02')]),
    session('s3', [run('r3', 's3', 'B', '2026-09-03')]), session('s4', [run('r4', 's4', undefined, '2026-09-04')]),
  ]);
  assert.deepEqual(result.events.map(x => [x.eventId, x.judgmentLoaded]), [['B', 1], ['A', 2]]);
  assert.equal(result.events[1].latestRunId, 'r2');
  assert.equal(result.events[1].businessTitle, '文泽路交通事故');
  assert.deepEqual(result.legacy.map(x => x.id), ['s4']);
  assert.equal(result.sessionsLoaded, 4);
  assert.equal(result.events[1].judgmentTotal, undefined);
});
test('new completed event outranks old active event; JSON normalized_event is accepted', () => {
  const a = run('old', 's1', 'A', '2026-08-01', 'running');
  const b = run('new', 's2', 'B', '2026-09-01'); b.normalized_event = JSON.stringify(b.normalized_event);
  assert.deepEqual(groupRecentJudgments([session('s1', [a]), session('s2', [b])]).events.map(x => x.eventId), ['B', 'A']);
});
test('zero unbound judgments hide the entire historical group and permanent empty paragraph', () => {
  for (const sessions of [[], [session('s1', [run('r1', 's1', 'A', '2026-09-01')])]]) {
    const rendered = recentHtml(groupRecentJudgments(sessions));
    assert.ok(!rendered.includes('历史研判（未关联事件）'));
    assert.ok(!rendered.includes('<details'));
    assert.ok(!rendered.includes('暂无关联事件的研判'));
    assert.match(rendered, /已加载最近/);
  }
});
test('two unbound judgments have a business label and no inferred event navigation', () => {
  const result = groupRecentJudgments([
    session('s1', [run('r1', 's1', undefined, '2026-09-01')]),
    session('s2', [run('r2', 's2', undefined, '2026-09-01')]),
  ]);
  const rendered = recentHtml(result);
  assert.equal(result.events.length, 0);
  assert.match(rendered, /历史研判（未关联事件）/);
  assert.match(rendered, /这些历史研判缺少可靠的事件关联信息，因此未合并到最近研判中。/);
  assert.equal((rendered.match(/<button /g) || []).length, 2);
  assert.ok(!rendered.includes('data-recent-event'));
  assert.ok(!rendered.includes('旧版'));
});
test('mixed session unbound entry targets the unbound run, never its newer event-bound run', () => {
  const result = groupRecentJudgments([session('s', [run('unbound', 's', undefined, '2026-09-01'), run('bound', 's', 'A', '2026-09-02')])]);
  assert.equal(result.legacy[0].unboundRunId, 'unbound');
  assert.equal(result.events[0].latestRunId, 'bound');
});
test('duplicates, missing/malformed event and failed requests are not invented relations', () => {
  const r = run('r', 's1', 'A', '2026-09-01');
  const result = groupRecentJudgments([session('s1', [r, r]), session('s2', [{ ...r, session_id: 's2', normalized_event: '{' }]), session('s3', [], { error: '503' })]);
  assert.equal(result.events[0].judgmentLoaded, 1);
  assert.equal(result.legacy[0].id, 's2');
  assert.equal(result.failedSessions[0].id, 's3');
  assert.equal(result.legacy.length, 1);
});
test('explicit target in old/target/new session wins; missing target never falls back', () => {
  const runs = ['old', 'target', 'new'].map((id, i) => run(id, 's', 'A', `2026-09-0${i + 1}`));
  assert.equal(selectJudgmentRun(runs, 'target'), 'target');
  assert.equal(selectJudgmentRun(runs, 'deleted'), 'deleted');
  assert.equal(selectJudgmentRun(runs), 'new');
});
test('exact detail validates run, session and explicit event independently', () => {
  const detail = { run: run('target', 's', 'A', '2026-09-01') };
  validateJudgmentDetail(detail, { runId: 'target', sessionId: 's', eventId: 'A' });
  validateJudgmentDetail(detail, { runId: 'target', sessionId: 's' });
  for (const selection of [{ runId: 'new', sessionId: 's' }, { runId: 'target', sessionId: 'other' }, { runId: 'target', sessionId: 's', eventId: 'B' }]) {
    assert.throws(() => validateJudgmentDetail(detail, selection), /不匹配/);
  }
});
test('four block states render independently and knowledge EMPTY is not error', () => {
  const model = present(context());
  assert.deepEqual(model.blocks.map(x => x.status), ['READY', 'READY', 'EMPTY', 'READY']);
  const rendered = html(model);
  for (const label of ['区域信息', '历史事件', '规则知识', '历史处置参考', '本次研判未检索到相关规则知识', '仅包含该事件创建时间之前的记录']) assert.ok(rendered.includes(label));
  assert.ok(!rendered.includes('获取失败'));
});
test('empty, unavailable, unresolved and legacy snapshot have distinct honest messages', () => {
  const c = context(); c.regionalContext.status = 'UNRESOLVED'; c.historicalContext.status = 'UNAVAILABLE'; c.caseMemoryContext.status = 'ERROR';
  const rendered = html(present(c));
  assert.match(rendered, /位置尚未确认/); assert.match(rendered, /未能获取历史事件上下文/); assert.match(rendered, /获取失败/);
  for (const absent of [undefined, null, {}, '{}']) assert.match(html(present(absent)), /该研判未记录分析时的上下文快照/);
  assert.match(html(present('{malformed')), /快照无法读取/);
});
test('streaming run without hydrated snapshot is loading, not a legacy assertion', () => {
  const rendered = renderToStaticMarkup(React.createElement(Panel, { loading: true }));
  assert.match(rendered, /正在载入本次研判快照/);
  assert.ok(!rendered.includes('旧版'));
});
test('reality labels come only from persisted provenance, not identifiers', () => {
  assert.equal(provenanceLabel({ eventId: 'synthetic_validation' }), '来源未核验');
  assert.equal(provenanceLabel({ documentId: 'real_public_verified' }), '来源未核验');
  assert.equal(provenanceLabel({ provenance: { sourceType: 'synthetic_validation' } }), '合成历史样本 · 用于验证');
  assert.equal(provenanceLabel({ provenance: { sourceType: 'real_public_source_grounded' } }), '公开法规/规则');
  assert.equal(provenanceLabel({ provenance: { sourceType: 'rag_v2_documents' } }), '来源未核验');
});
test('five available refs and two output refs never claim all were used', () => {
  const c = context(); c.groundingRefs = [1, 2, 3, 4, 5].map(n => ({ evidenceId: 'ref' + n }));
  const tasks = [{ input_snapshot: { groundingEvidenceRefs: c.groundingRefs.slice(0, 2), groundingFacts: ['背景'] }, output_snapshot: { evidence_refs: c.groundingRefs.slice(0, 2) } }];
  const model = present(c, tasks);
  assert.equal(model.availableRefCount, 5); assert.equal(model.outputRefCount, 2);
  assert.equal(model.inputRefCount, 2);
  assert.match(html(model), /实际使用情况未单独记录/);
  assert.equal(model.usageUnverified, true);
  assert.ok(!html(model).includes('使用了这些依据'));
});
test('rejected cases remain rejected, completed means workflow complete not road solved', () => {
  const c = context(); c.caseMemoryContext.cases.push({ finalStatus: 'completed', eventType: 'congestion' });
  const rendered = html(present(c));
  assert.match(rendered, /已驳回/); assert.match(rendered, /已完成流程/);
  assert.ok(!/成功经验|已解决|有效案例/.test(rendered));
});
test('knowledge source identity is explicit; title-only evidence has no navigation', () => {
  const c = context(); c.knowledgeContext = { status: 'READY', provenance: { sourceType: 'real_public_source_grounded' }, evidence: [{ title: '明确规则', documentId: 'doc-exact', excerpt: '<script>bad</script>' }, { title: '仅标题' }] };
  const rendered = html(present(c));
  assert.equal((rendered.match(/查看当前知识详情/g) || []).length, 1);
  assert.ok(!rendered.includes('<script>')); assert.match(rendered, /公开法规\/规则/);
});
test('selected run renders its knowledge and case snapshots even after current sources change', async () => {
  const c = context();
  c.knowledgeContext = { status: 'READY', evidence: [{ documentId: 'doc-exact', title: '知识 A', excerpt: '当时规则 A' }] };
  c.caseMemoryContext.cases = [{ caseId: 'case-exact', eventType: 'accident', finalStatus: 'rejected', generatedSummary: '当时案例 A' }];
  const persisted = JSON.stringify(c);
  const currentSources = { knowledge: c.knowledgeContext.evidence[0], case: c.caseMemoryContext.cases[0] };
  currentSources.knowledge.title = '当前知识 B';
  currentSources.case.generatedSummary = '当前案例 B';
  let rendered;
  loadJudgmentSelection({ sessionId: 's', runId: 'target' }, async () => ({ run: { ...run('target', 's', 'A', '2026-09-01'), grounding_context: persisted } }), detail => { rendered = html(present(detail.run.grounding_context)); }, assert.fail);
  await tick();
  assert.match(rendered, /知识 A/); assert.match(rendered, /当时案例 A/);
  assert.ok(!rendered.includes('当前知识 B')); assert.ok(!rendered.includes('当前案例 B'));
  assert.match(rendered, /本次研判时的上下文/);
});
test('slow run A cannot replace selected B snapshot after cleanup', async () => {
  const slow = deferred(); let selected;
  const cancel = loadJudgmentSelection({ sessionId: 's', runId: 'A' }, () => slow.promise, detail => { selected = detail; }, assert.fail);
  cancel();
  const b = { run: run('B', 's', 'B-event', '2026-09-01'), grounding: 'B snapshot' };
  loadJudgmentSelection({ sessionId: 's', runId: 'B' }, async () => b, detail => { selected = detail; }, assert.fail);
  await tick(); slow.resolve({ run: run('A', 's', 'A-event', '2026-09-01'), grounding: 'A snapshot' }); await tick();
  assert.equal(selected, b);
});
test('late errors after selection cleanup cannot replace current detail', async () => {
  const slow = deferred(); let errors = 0;
  const cancel = loadJudgmentSelection({ sessionId: 's', runId: 'A' }, () => slow.promise, assert.fail, () => errors++);
  cancel(); slow.reject(new Error('late 404')); await tick(); assert.equal(errors, 0);
});
test('missing requested run reports error without querying latest', async () => {
  const ids = []; let message;
  loadJudgmentSelection({ sessionId: 's', runId: 'missing' }, async id => { ids.push(id); throw new Error('研判未找到 / 已删除'); }, assert.fail, value => { message = value; });
  await tick(); assert.deepEqual(ids, ['missing']); assert.equal(message, '研判未找到 / 已删除');
});
