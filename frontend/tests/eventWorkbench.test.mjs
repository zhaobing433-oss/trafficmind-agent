import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Compile the production helper with the existing TypeScript dependency; no test framework required.
const source = readFileSync(new URL('../src/components/simulation/eventWorkbenchState.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { loadEventRelations, pendingRelations, relationsForSelection, derivePrimaryAction, eventSourceLabel, verifiedJudgmentSessionId } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const plan = (eventId = 'A') => ({ planId: 'plan-a', eventId, goal: '事故处置', updatedAt: '2026-09-01', createdAt: '2026-09-01' });
const judgment = (status = 'completed') => ({ run_id: 'judgment-a', session_id: 'session-a', status, normalized_event: { eventId: 'A' }, started_at: '2026-09-01' });
const run = status => ({ runId: 'run-a', status, definitionId: 'plan-a', startedAt: '2026-09-01' });
const ok = items => ({ status: items.length ? 'SUCCESS_WITH_DATA' : 'SUCCESS_EMPTY', items, total: items.length });
const resolved = (collaboration = [], plans = [], workflow = []) => ({ ...pendingRelations('A', 0), collaboration: ok(collaboration), plan: ok(plans), workflow: ok(workflow) });
const sources = (overrides = {}) => ({
  collaboration: async eventId => ({ eventId, total: 0, runs: [] }),
  plan: async () => ({ total: 0, plans: [] }),
  planDetail: async planId => ({ definitionId: planId, plan: { ...plan(), planId, definitionStatus: 'active', steps: [{ approvalRequired: true }], metadata: { sourceAgent: { sessionId: 'plan-source-session' } } } }),
  workflow: async () => ({ total: 0, runs: [] }),
  ...overrides,
});
async function query(overrides = {}) {
  let state;
  const cancel = loadEventRelations('A', 0, sources(overrides), next => { state = next; });
  await tick();
  return { get state() { return state; }, cancel };
}

test('IDLE and LOADING never expose a creation action', () => {
  for (const eventId of [null, 'A']) {
    const action = derivePrimaryAction(pendingRelations(eventId, 0));
    assert.equal(action.creates, false);
    assert.equal(action.kind, 'none');
  }
});

for (const key of ['collaboration', 'plan', 'workflow']) {
  test(key + ' request failure is ERROR, not success empty', async () => {
    const result = await query({ [key]: async () => { throw new Error('503'); } });
    assert.equal(result.state[key].status, 'ERROR');
    assert.equal(result.state[key].total, null);
    assert.equal(derivePrimaryAction(result.state).creates, false);
    assert.equal(derivePrimaryAction(result.state).kind, 'retry');
  });
  test(key + ' pending blocks creation until every required query succeeds', async () => {
    const slow = deferred();
    const result = await query({ [key]: () => slow.promise });
    assert.equal(result.state[key].status, 'LOADING');
    assert.equal(derivePrimaryAction(result.state).kind, 'none');
    slow.resolve(key === 'plan' ? { total: 0, plans: [] } : { eventId: 'A', total: 0, runs: [] });
    await tick();
    assert.equal(result.state[key].status, 'SUCCESS_EMPTY');
    assert.equal(derivePrimaryAction(result.state).kind, 'analysis');
  });
}

test('successful zero counts enable analysis, not before', async () => {
  const result = await query();
  assert.equal(derivePrimaryAction(result.state).kind, 'analysis');
  assert.equal(result.state.plan.total, 0);
});

test('event A cannot use global-latest plan belonging to B', async () => {
  const result = await query({ plan: async () => ({ total: 1, plans: [plan('B')] }) });
  assert.equal(result.state.plan.status, 'ERROR');
  assert.deepEqual(result.state.plan.items, []);
  assert.equal(derivePrimaryAction(result.state).creates, false);
});

test('mismatched plan detail also blocks execution', async () => {
  const result = await query({ plan: async () => ({ total: 1, plans: [plan()] }), planDetail: async () => ({ definitionId: 'plan-a', plan: plan('B') }) });
  assert.equal(result.state.plan.status, 'ERROR');
  assert.equal(derivePrimaryAction(result.state).creates, false);
});

test('plan detail is required, and its source session is preserved', async () => {
  const slow = deferred();
  const result = await query({ plan: async () => ({ total: 1, plans: [plan()] }), planDetail: () => slow.promise });
  assert.equal(derivePrimaryAction(result.state).kind, 'none');
  slow.resolve(await sources().planDetail('plan-a'));
  await tick();
  assert.equal(derivePrimaryAction(result.state).kind, 'execute');
  assert.equal(result.state.plan.items[0].detail.metadata.sourceAgent.sessionId, 'plan-source-session');
});

test('all queries receive the selected event ID, including workflow', async () => {
  const requested = [];
  const base = sources();
  const result = await query(Object.fromEntries(['collaboration', 'plan', 'workflow'].map(key => [key, id => { requested.push([key, id]); return base[key](id); }])));
  assert.deepEqual(requested, [['collaboration', 'A'], ['plan', 'A'], ['workflow', 'A']]);
  assert.equal(result.state.eventId, 'A');
});

test('collaboration linkage uses explicit normalized_event, never session inference', async () => {
  for (const normalized_event of [{ eventId: 'B' }, '{}', undefined]) {
    const result = await query({ collaboration: async () => ({ eventId: 'A', total: 1, runs: [{ ...judgment(), normalized_event }] }) });
    assert.equal(result.state.collaboration.status, 'ERROR');
    assert.equal(derivePrimaryAction(result.state).creates, false);
  }
});

test('partial pages retain truthful total; invalid pages never imply empty', async () => {
  const result = await query({ workflow: async () => ({ total: 65, runs: [run('running')] }) });
  assert.equal(result.state.workflow.total, 65);
  assert.equal(result.state.workflow.items.length, 1);
  for (const response of [{ total: 5, runs: [] }, { total: 0 }, { total: -1, runs: [] }, { total: 2, runs: [run('running'), run('running')] }]) {
    const invalid = await query({ workflow: async () => response });
    assert.equal(invalid.state.workflow.status, 'ERROR');
  }
});

test('late event A responses cannot overwrite event B after cleanup', async () => {
  const slow = deferred();
  let selected;
  const cancelA = loadEventRelations('A', 0, sources({ plan: () => slow.promise }), state => { selected = state; });
  await tick();
  cancelA();
  loadEventRelations('B', 0, sources(), state => { selected = state; });
  await tick();
  const before = selected;
  slow.resolve({ total: 1, plans: [plan()] });
  await tick();
  assert.equal(selected, before);
  assert.equal(selected.eventId, 'B');
  assert.equal(selected.plan.status, 'SUCCESS_EMPTY');
});

test('the selection render and retry render mask old successful state before effects', () => {
  const state = resolved([], [{ ...plan(), detail: { definitionStatus: 'active' } }]);
  for (const [eventId, revision] of [['B', 0], ['A', 1], [null, 0]]) {
    const next = relationsForSelection(state, eventId, revision);
    assert.equal(next.plan.items.length, 0);
    assert.equal(derivePrimaryAction(next).creates, false);
  }
});

test('unmount cancellation ignores failures too', async () => {
  const slow = deferred();
  let changes = 0;
  const cancel = loadEventRelations('A', 0, sources({ workflow: () => slow.promise }), () => { changes++; });
  await tick();
  cancel();
  const count = changes;
  slow.reject(new Error('late network error'));
  await tick();
  assert.equal(changes, count);
});

test('stage-aware action matrix', () => {
  const matrix = [
    [resolved(), 'analysis', true],
    [resolved([judgment('running')]), 'view_judgment', false],
    [resolved([judgment()]), 'plan', true],
    [resolved([], [{ ...plan(), detail: { definitionStatus: 'active' } }]), 'execute', true],
    [resolved([], [{ ...plan(), detail: { definitionStatus: 'draft' } }]), 'view_plan', false],
    ...['running', 'awaiting_approval', 'completed', 'rejected', 'failed', 'cancelled'].map(status => [resolved([], [], [run(status)]), 'view_workflow', false]),
  ];
  for (const [state, kind, creates] of matrix) {
    assert.equal(derivePrimaryAction(state).kind, kind);
    assert.equal(derivePrimaryAction(state).creates, creates);
  }
  assert.equal(derivePrimaryAction(resolved([], [], [run('awaiting_approval')])).label, '去审批');
  assert.equal(derivePrimaryAction(resolved([], [], [run('rejected')])).label, '查看驳回原因');
});

test('completed event judgment remains a verified secondary action while plan is primary', () => {
  const state = resolved([judgment()]);
  assert.equal(derivePrimaryAction(state).kind, 'plan');
  assert.equal(verifiedJudgmentSessionId(state), 'session-a');
  assert.equal([derivePrimaryAction(state)].length, 1);
});

test('judgment secondary action is exact to the selected event session', () => {
  const state = resolved([
    { ...judgment(), run_id: 'judgment-b', session_id: 'session-b', normalized_event: { eventId: 'B' }, started_at: '2026-09-02' },
    { ...judgment(), session_id: 'session-a' },
  ]);
  assert.equal(verifiedJudgmentSessionId(state), 'session-a');
});

test('judgment secondary visibility follows relation state and does not replace later-stage primary actions', () => {
  const base = resolved([judgment()]);
  for (const collaboration of [
    { status: 'IDLE', items: [], total: null },
    { status: 'LOADING', items: [], total: null },
    { status: 'SUCCESS_EMPTY', items: [], total: 0 },
    { status: 'ERROR', items: [], total: null, error: 'offline' },
  ]) assert.equal(verifiedJudgmentSessionId({ ...base, collaboration }), null);

  const withPlan = resolved([judgment()], [{ ...plan(), detail: { definitionStatus: 'active' } }]);
  assert.equal(derivePrimaryAction(withPlan).kind, 'execute');
  assert.equal(verifiedJudgmentSessionId(withPlan), 'session-a');

  const withWorkflow = resolved([judgment()], [], [run('awaiting_approval')]);
  assert.equal(derivePrimaryAction(withWorkflow).kind, 'view_workflow');
  assert.equal(derivePrimaryAction(withWorkflow).label, '去审批');
  assert.equal(verifiedJudgmentSessionId(withWorkflow), 'session-a');
});

test('known resources do not enable creation when another required query errors', () => {
  const state = resolved([judgment()], [{ ...plan(), detail: { definitionStatus: 'active' } }]);
  state.workflow = { status: 'ERROR', total: null, items: [], error: 'offline' };
  assert.equal(derivePrimaryAction(state).kind, 'retry');
  assert.equal(state.plan.items[0].eventId, 'A');
});

test('provenance labeling never guesses from IDs or persistence', () => {
  assert.equal(eventSourceLabel({ eventId: 'synthetic_validation_123' }), '来源未核验');
  assert.equal(eventSourceLabel({ sourceType: 'event_records' }), '来源未核验');
  assert.equal(eventSourceLabel({ rawEvent: { provenance: { sourceType: 'synthetic_validation' } } }), '合成验证事件');
});
