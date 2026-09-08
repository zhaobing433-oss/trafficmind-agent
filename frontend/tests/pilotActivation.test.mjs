import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './loadTs.mjs';

const root = new URL('../../', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, root), 'utf8'));
const publicEvents = json('backend/data/pilot_history_public/qt_by_xiasha_pilot_001/events.json').events;
const sources = json('backend/data/pilot_history_public/qt_by_xiasha_pilot_001/source_register.json').sources;
const manifest = json('backend/data/pilot_demo/qt_by_xiasha_pilot_001/demo_manifest.json');
const holdout = json('backend/data/pilot_holdout/qt_by_xiasha_pilot_001/holdout_events.json').events;
const judgment = loadTs(new URL('../src/utils/judgment.ts', import.meta.url));
const eventReality = loadTs(new URL('../src/components/simulation/eventReality.ts', import.meta.url));

test('public history and system replay use distinct truthful labels', () => {
  assert.equal(judgment.provenanceLabel({ provenance: { sourceType: 'real_public_reported_incident' } }), '公开历史事件');
  assert.equal(judgment.provenanceLabel({ sourceType: 'public_incident_replay_system_closure' }), '公开历史事件 · 系统回放案例');
  assert.equal(judgment.provenanceLabel({ sourceType: 'synthetic_event_system_closure' }), '系统闭环验证案例');
  assert.equal(judgment.provenanceLabel({ provenance: { sourceType: 'synthetic_validation' } }), '合成历史样本 · 用于验证');
  assert.equal(judgment.caseOutcome('rejected'), '已驳回');
});

test('event detail source label distinguishes public history from Pilot validation data', () => {
  const source = readFileSync(new URL('../src/components/simulation/eventWorkbenchState.ts', import.meta.url), 'utf8');
  assert.match(source, /sources\.includes\('real_public_reported_incident'\).*'公开历史事件'/);
  assert.match(source, /sources\.includes\('synthetic_validation'\).*'合成历史样本 · 用于验证'/s);
  assert.match(source, /synthetic_validation_holdout.*'合成验证事件'/s);
});

test('public history source registry is traceable and contains no Tier D source', () => {
  const sourceIds = new Set(sources.map(source => source.sourceId));
  assert.equal(publicEvents.length, 4);
  assert.ok(publicEvents.every(event => sourceIds.has(event.sourceId)));
  assert.ok(sources.every(source => ['A', 'B', 'C'].includes(source.sourceTier)));
  assert.ok(sources.every(source => source.sourceUri.startsWith('https://')));
});

test('demo current-event filters derive only from referenced Qiantang holdout rows', () => {
  const byId = new Map(holdout.map(event => [event.eventId, event]));
  const current = manifest.currentEventIds.map(id => byId.get(id));
  assert.ok(current.every(Boolean));
  assert.equal(current.length, 8);
  assert.equal(new Set(current.map(event => event.eventType)).size, 6);
  assert.ok(current.every(event => event.validation.expectedCanonicalLocation.regionId === manifest.regionId));
  const serialized = JSON.stringify(current);
  for (const legacy of ['人民路', '中山路', '演示大道', 'string', 'test']) assert.ok(!serialized.includes(legacy));
  assert.equal(eventReality.isCurrentEventRecord({ sourceType: 'synthetic_validation_holdout' }), true);
  assert.equal(eventReality.isCurrentEventRecord({ sourceType: 'real_public_reported_incident' }), false);
  assert.equal(eventReality.isCurrentEventRecord({ sourceType: 'synthetic_validation' }), false);
  assert.equal(eventReality.isCurrentEventRecord({}), true);
  const panel = readFileSync(new URL('../src/components/simulation/RealEventsPanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /records\.filter\(isCurrentEventRecord\)/);
});

test('modern public vector style is default with raster and topology fallback', () => {
  const config = readFileSync(new URL('../src/components/map/mapConfig.ts', import.meta.url), 'utf8');
  const view = readFileSync(new URL('../src/components/map/RealMapView.tsx', import.meta.url), 'utf8');
  const panel = readFileSync(new URL('../src/components/map/PilotMapPanel.tsx', import.meta.url), 'utf8');
  assert.match(config, /tiles\.openfreemap\.org\/styles\/positron/);
  assert.match(config, /VITE_MAP_STYLE_URL/);
  assert.match(config, /tile\.openstreetmap\.org/);
  assert.match(view, /setStyle\(fallbackMapStyle\(\)\)/);
  assert.match(view, /data-map-provider/);
  assert.match(panel, /切换到拓扑视图/);
  assert.match(panel, /OpenFreeMap/);
  assert.ok(!config.includes('Apple'));
});

test('Qiantang launcher explicitly binds the frontend and labels the validation environment', () => {
  const launcher = readFileSync(new URL('../../scripts/start-qiantang-demo.sh', import.meta.url), 'utf8');
  const vite = readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8');
  const workspace = readFileSync(new URL('../src/components/simulation/TrafficMapWorkspace.tsx', import.meta.url), 'utf8');
  assert.match(launcher, /VITE_PROXY_TARGET="\$BACKEND_URL"/);
  assert.match(launcher, /VITE_RUNTIME_PROFILE="qiantang-demo"/);
  assert.match(launcher, /--strictPort/);
  assert.match(vite, /Qiantang demo requires an explicit VITE_PROXY_TARGET/);
  assert.match(workspace, /runtimeEnv\.VITE_RUNTIME_PROFILE === 'qiantang-demo'/);
  assert.match(workspace, /钱塘 Pilot/);
  assert.match(workspace, /验证数据环境/);
  assert.match(workspace, /\? '演练模式' : '返回事件工作台'/);
  for (const legacy of ['人民路', '中山路', '演示大道']) {
    assert.ok(!workspace.includes(legacy));
  }
});

test('history and case detail panels fetch persisted provenance instead of relabeling snapshots', () => {
  const source = readFileSync(new URL('../src/components/collaboration/GroundingEvidencePanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /\/api\/event\//);
  assert.match(source, /\/api\/case-memory\//);
  assert.match(source, /公开事件事实 · TrafficMind 系统验证回放，不是历史真实处置/);
  assert.match(source, /实际交通处置效果：未记录/);
});
