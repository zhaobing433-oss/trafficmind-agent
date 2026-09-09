import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { loadTs } from './loadTs.mjs';

const { judgmentPlans, planSource, validatePlan, validateWorkflow, exactPendingApproval, workflowSourcePlan, loadClosedLoopSelection, executionStatus, closureRecordNotice } = loadTs(new URL('../src/utils/closedLoop.ts', import.meta.url));
const { PlanSteps } = loadTs(new URL('../src/components/planning/PlanSteps.tsx', import.meta.url));
const { ExecutionSummary } = loadTs(new URL('../src/components/workflow/ExecutionSummary.tsx', import.meta.url));
const { ApprovalActionSummary } = loadTs(new URL('../src/components/workflow/ApprovalActionSummary.tsx', import.meta.url));
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const plan = (id = 'planA', eid = 'A', rid = 'judgmentA') => ({ planId: id, goal: '现场安全处置方案', eventId: eid, version: 1, metadata: { sourceAgent: { sessionId: 's', collaborationRunId: rid } }, steps: [{ stepId: 'notify', stepType: 'action', objective: '通知现场人员', approvalRequired: true, expectedOutcome: '记录通知结果' }] });
const response = p => ({ plan: p, definitionId: p.planId, runs: [] });
const workflow = (rid = 'runA', eid = 'A', pid = 'planA', status = 'awaiting_approval') => ({ run: { runId: rid, definitionId: pid, status }, state: { workflowRunId: rid, currentEvent: { eventId: eid, roadName: '文泽路', eventType: 'accident' }, pendingApproval: { workflowRunId: rid, approvalId: 'approval-' + rid, decision: 'pending', proposedActions: [{ actionType: 'notify_dingtalk' }] } }, nodeRuns: [], events: [], actionRecords: [] });

test('judgment A selects only its persisted plan, never a newer same-event judgment plan', async () => {
  const a = plan(), newer = plan('newer', 'A', 'judgmentNew'); const calls = [];
  const found = await judgmentPlans('A', 's', 'judgmentA', { list: async q => { calls.push(q); return { plans: [newer, a], total: 2 }; }, detail: async id => response(id === a.planId ? a : newer) });
  assert.deepEqual(found.map(x => x.planId), ['planA']);
  assert.equal(calls[0].eventId, 'A');
  assert.deepEqual(planSource(a), { sessionId: 's', runId: 'judgmentA', eventId: 'A' });
});
test('judgment plan query reads subsequent pages before asserting no exact plan', async () => {
  const calls = [];
  const result = await judgmentPlans('A', 's', 'judgmentA', { list: async ({ page }) => { calls.push(page); return { total: 2, plans: [plan(page === 1 ? 'other' : 'target', 'A', page === 1 ? 'other' : 'judgmentA')] }; }, detail: async id => response(plan(id, 'A', id === 'target' ? 'judgmentA' : 'other')) });
  assert.deepEqual(calls, [1, 2]); assert.equal(result[0].planId, 'target');
});
test('cross-event plan list and detail mismatches are errors, not empty relations', async () => {
  for (const sources of [
    { list: async () => ({ plans: [plan('B', 'B')], total: 1 }), detail: async () => response(plan()) },
    { list: async () => ({ plans: [plan()], total: 1 }), detail: async () => response(plan('B', 'B')) },
  ]) await assert.rejects(judgmentPlans('A', 's', 'judgmentA', sources), /关联/);
});
test('plan list/detail failures cannot advance closed loop or report no plan', async () => {
  for (const part of ['list', 'detail']) {
    const sources = { list: async () => ({ plans: [plan()], total: 1 }), detail: async () => response(plan()) };
    sources[part] = async () => { throw new Error('503'); };
    await assert.rejects(judgmentPlans('A', 's', 'judgmentA', sources), /503/);
  }
});
test('missing persisted source never infers latest judgment', () => {
  assert.equal(planSource({ ...plan(), metadata: {} }), null);
  assert.throws(() => validatePlan(response(plan('B')), 'planA'), /不匹配/);
});
test('workflow source uses exact definition and event, never latest plan', async () => {
  const calls = [];
  assert.equal((await workflowSourcePlan(workflow(), async id => { calls.push(id); return response(plan()); })).planId, 'planA');
  assert.deepEqual(calls, ['planA']);
  await assert.rejects(workflowSourcePlan(workflow(), async () => response(plan('planA', 'B'))), /不匹配/);
});
test('non-plan metadata is explicit 400; missing definition and transport failure remain errors', async () => {
  assert.equal(await workflowSourcePlan(workflow(), async () => { throw new Error('get plan failed: 400'); }), null);
  for (const code of [404, 503]) await assert.rejects(workflowSourcePlan(workflow(), async () => { throw new Error('get plan failed: ' + code); }), new RegExp(String(code)));
});
test('two pending approvals lock to exact workflow and approval identity', () => {
  const a = workflow(), b = workflow('runB', 'B', 'planB');
  assert.equal(exactPendingApproval(a, 'runA', 'approval-runA').workflowRunId, 'runA');
  assert.throws(() => exactPendingApproval(b, 'runA', 'approval-runA'), /不匹配/);
  assert.throws(() => exactPendingApproval(a, 'runA', 'approval-runB'), /已变化/);
  a.state.pendingApproval.workflowRunId = 'runB';
  assert.throws(() => exactPendingApproval(a, 'runA'), /已变化/);
});
test('rejected run never exposes an actionable pending approval or completed result', () => {
  const detail = workflow('runA', 'A', 'planA', 'rejected');
  assert.throws(() => exactPendingApproval(detail, 'runA'), /已变化/);
  const html = render(ExecutionSummary, { detail, plan: plan() });
  assert.match(html, /已驳回/); assert.ok(!/流程已完成|处置成功|事件已解决/.test(html));
});
test('completed workflow reports system completion, not real-world success', () => {
  const html = render(ExecutionSummary, { detail: workflow('runA', 'A', 'planA', 'completed'), plan: plan() });
  assert.match(html, /流程已完成/); assert.match(html, /实际交通处置效果未记录/);
  assert.ok(!/处置成功|事件解决|拥堵缓解/.test(html));
});
test('failed workflow is terminal and has no automatic restart command', () => {
  const html = render(ExecutionSummary, { detail: workflow('runA', 'A', 'planA', 'failed'), plan: plan() });
  assert.match(html, /执行失败/); assert.ok(!/重新启动|重新执行|批准/.test(html));
});
test('historical grounding Case X is never presented as current closure Case Y', () => {
  const detail = workflow('runA', 'A', 'planA', 'completed');
  detail.state.groundingContext = { caseMemoryContext: { cases: [{ caseId: 'X', generatedSummary: '历史案例 X' }] } };
  detail.state.similarCase = { caseId: 'Y' };
  const html = render(ExecutionSummary, { detail, plan: plan() });
  assert.match(html, /尚无法确认是否形成历史处置记录/);
  assert.ok(!html.includes('历史案例 X')); assert.ok(!html.includes('已沉淀为历史处置参考'));
  assert.match(closureRecordNotice('rejected'), /本次流程已结束/);
});
test('plan steps show projected statuses, approval requirements and rejected proposals honestly', () => {
  const p = plan(); p.metadata.agentRecommendationAudit = { rejected: [{ actionType: 'unknown', reason: 'unsupported_action' }] };
  const html = render(PlanSteps, { plan: p, run: { version: 1, stepStatuses: { notify: 'denied' } } });
  for (const value of ['通知现场人员', '记录通知结果', '需要人工审批', '不可执行', '当前不支持此操作']) assert.ok(html.includes(value));
  assert.ok(!html.includes('启动执行'));
  assert.match(render(PlanSteps, { plan: p, run: { version: 2, stepStatuses: { notify: 'succeeded' } } }), /执行状态未记录/);
});
test('approval business details preserve risk zero and do not invent reasons', () => {
  const html = render(ApprovalActionSummary, { action: { actionType: 'notify_dingtalk', params: { message: '核实现场' } }, context: { roadName: '文泽路', riskScore: 0 } });
  assert.match(html, /风险评分 0/); assert.match(html, /已有理由：未记录/); assert.match(html, /核实现场/);
  assert.ok(!html.includes('推荐批准'));
});
test('terminal plan execution does not advertise a projected ready step as executable', () => {
  for (const status of ['rejected', 'failed', 'cancelled', 'completed']) {
    const html = render(PlanSteps, { plan: plan(), run: { version: 1, status, stepStatuses: { notify: 'ready' } } });
    assert.match(html, /流程已结束，不继续执行/);
    assert.ok(!html.includes('class="execution-badge">具备执行条件'));
    assert.match(html, /流程结束时的记录/);
  }
});
for (const resource of ['Plan', 'Workflow', 'Approval']) test(`${resource} A slow / B fast ignores late A detail and error after selection cleanup`, async () => {
  const a = deferred(); let visible;
  const cancel = loadClosedLoopSelection(() => a.promise, value => { visible = value; }, assert.fail);
  cancel();
  loadClosedLoopSelection(async () => 'B', value => { visible = value; }, assert.fail);
  await tick(); a.resolve('A'); await tick(); assert.equal(visible, 'B');
  const error = deferred(); const stop = loadClosedLoopSelection(() => error.promise, assert.fail, assert.fail);
  stop(); error.reject(new Error('late')); await tick();
});
test('workflow detail identity and status enum are explicit', () => {
  assert.throws(() => validateWorkflow(workflow('B'), 'A'), /不匹配/);
  assert.equal(executionStatus('awaiting_approval'), '等待人工审批');
  assert.equal(executionStatus('invented'), '状态未记录');
});
