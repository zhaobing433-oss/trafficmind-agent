import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { loadTs } from './loadTs.mjs';
const { pilotGeography: geo } = loadTs(new URL('../src/data/pilot/pilotGeography.ts', import.meta.url));
const { locateEvent, validCoordinates, pilotBounds, shouldFocusEvent, loadEventLocations, DEFAULT_SPATIAL_VIEW } = loadTs(new URL('../src/components/map/mapLocation.ts', import.meta.url));
const { SessionManagement } = loadTs(new URL('../src/components/collaboration/SessionManagement.tsx', import.meta.url));
const Sidebar = loadTs(new URL('../src/components/Sidebar.tsx', import.meta.url)).default;
const pack = JSON.parse(readFileSync(new URL('../../backend/data/pilot_regions/qt_by_xiasha_pilot_001/intersections.json', import.meta.url)));
const binding = (eventId = 'A', index = 0) => ({ binding: { eventId, bindingId: 'binding-' + eventId, regionId: geo.metadata.regionId, intersectionId: pack[index].intersectionId, status: 'resolved', resolvedAt: '2026-09-07' }, locationContext: { intersection: pack[index] } });

test('all map points exactly match G1 inventory, coordinates and public OSM provenance', () => {
  assert.equal(geo.features.length, 9);
  assert.equal(new Set(geo.features.map(f => f.id)).size, 9);
  for (const f of geo.features) {
    const row = pack.find(p => p.intersectionId === f.id); assert.ok(row);
    assert.equal(f.geometry.type, 'Point'); assert.ok(validCoordinates(f.geometry.coordinates));
    assert.deepEqual(f.geometry.coordinates, [row.longitude, row.latitude]);
    assert.deepEqual(f.properties.osmNodeIds, row.metadata.osmNodeIds);
    assert.equal(f.properties.verifiedAt, row.verifiedAt);
    assert.ok(f.properties.sourceReference); assert.equal(f.properties.coordinateSystem, 'WGS84');
  }
  assert.equal(geo.metadata.purpose, 'visualization_only'); assert.equal(geo.metadata.license, 'ODbL-1.0');
  assert.match(geo.metadata.source.sourceUrl, /^https:/);
});
test('invalid coordinates reject non-finite and out-of-range values', () => {
  for (const c of [[181, 0], [0, 91], [NaN, 30], [120, Infinity], [120]]) assert.equal(validCoordinates(c), false);
});
test('pilot viewport derives from verified points, not approximate region bounds', () => {
  const bounds = pilotBounds();
  for (const f of geo.features) { const [x, y] = f.geometry.coordinates; assert.ok(x >= bounds[0][0] && x <= bounds[1][0] && y >= bounds[0][1] && y <= bounds[1][1]); }
});
test('intersection-bound A and B resolve to their own authoritative location', () => {
  assert.deepEqual(locateEvent('A', binding()).coordinates, geo.features[0].geometry.coordinates);
  assert.deepEqual(locateEvent('B', binding('B', 4)).coordinates, geo.features[4].geometry.coordinates);
  assert.throws(() => locateEvent('A', binding('B')), /不匹配/);
});
test('unresolved or superseded binding cannot use historical matching coordinates', () => {
  for (const status of ['unresolved', 'ambiguous', 'superseded', '']) {
    const value = binding(); value.binding.status = status; value.history = [binding().binding];
    assert.equal(locateEvent('A', value), null);
  }
});
test('road-bound and road-name-only events never get centroid markers', () => {
  const value = binding(); delete value.binding.intersectionId; value.binding.roadId = 'QT_BY_RD_WENZE'; value.binding.roadName = '文泽路';
  assert.equal(locateEvent('A', value), null);
  assert.throws(() => locateEvent('A', { roadName: '文泽路', longitude: 120.34, latitude: 30.31 }), /不匹配/);
});
test('wrong region, removed intersection, missing provenance or coordinate drift does not place marker', () => {
  for (const modify of [x => { x.binding.regionId = 'other'; }, x => { x.binding.resolvedAt = ''; }, x => { x.locationContext.intersection = {}; }, x => { x.locationContext.intersection = { ...pack[0], longitude: 120 }; }, x => { x.locationContext.intersection = { ...pack[0], status: 'inactive' }; }]) {
    const value = binding(); modify(value); assert.equal(locateEvent('A', value), null);
  }
});
test('camera moves only for a new exact event, not ordinary refresh or stale A location', () => {
  const a = locateEvent('A', binding()), b = locateEvent('B', binding('B', 4));
  assert.equal(shouldFocusEvent(null, 'A', a), true);
  assert.equal(shouldFocusEvent('A', 'A', a), false);
  assert.equal(shouldFocusEvent('A', 'B', b), true);
  assert.equal(shouldFocusEvent('A', 'B', a), false);
  assert.equal(shouldFocusEvent('A', 'B'), false);
});
test('location request 404 is unlocated; 503 and mismatched response remain errors', async () => {
  const results = {};
  await loadEventLocations(['A', 'B', 'C'], new AbortController().signal, (id, value) => { results[id] = value.kind; }, async url => new Response(url.includes('/C/') ? JSON.stringify(binding('A')) : '', { status: url.includes('/A/') ? 404 : url.includes('/B/') ? 503 : 200 }));
  assert.deepEqual(results, { A: 'unlocated', B: 'error', C: 'error' });
});
test('cancelled location batch does not publish late markers', async () => {
  let release; const pending = new Promise(r => { release = r; }); const controller = new AbortController();
  const task = loadEventLocations(['A'], controller.signal, assert.fail, async () => { await pending; return new Response(JSON.stringify(binding())); });
  controller.abort(); release(); await task;
});
test('default is real map and map library remains behind lazy import', () => {
  assert.equal(DEFAULT_SPATIAL_VIEW, 'map');
  const panel = readFileSync(new URL('../src/components/map/PilotMapPanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /lazy\(\(\) => import\('\.\/RealMapView'\)\)/);
  assert.ok(!panel.includes("from 'maplibre-gl'"));
  assert.match(panel, /地图暂时无法加载/); assert.match(panel, /切换到拓扑视图/);
  const view = readFileSync(new URL('../src/components/map/RealMapView.tsx', import.meta.url), 'utf8');
  assert.match(view, /maplibre-gl-worker\.mjs\?worker&url/);
  assert.match(view, /setWorkerUrl\(workerUrl\)/);
});
test('Traffic sidebar has event-centric recent judgments but no session management', () => {
  const html = renderToStaticMarkup(React.createElement(Sidebar, { collapsed: false, activeView: 'simulation', recentList: [], judgments: { events: [], legacy: [], failedSessions: [], sessionsLoaded: 0 }, judgmentsLoading: false, onRecentClick() {}, onOpenJudgment() {} }));
  assert.match(html, /最近研判/); assert.ok(!html.includes('会话记录与管理')); assert.ok(!html.includes('历史研判（未关联事件）'));
});
test('collaboration management is folded, with open/rename/delete retained', () => {
  const html = renderToStaticMarkup(React.createElement(SessionManagement, { sessions: [{ id: 's', title: '现场研判记录', mode: 'collaboration', updatedAt: 1 }], onOpen() {}, onRename() {}, onDelete() {} }));
  assert.match(html, /会话管理/); assert.match(html, /现场研判记录/); assert.match(html, /重命名会话/); assert.match(html, /删除会话/); assert.ok(!html.includes('<details open'));
});
