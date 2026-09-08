import React, { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { EnvironmentOutlined, ApartmentOutlined } from '@ant-design/icons';
import { DEFAULT_SPATIAL_VIEW, loadEventLocations, type MapEvent, type LocationResult } from './mapLocation';
import './realMap.css';

const RealMapView = lazy(() => import('./RealMapView'));
class MapBoundary extends React.Component<{ children: React.ReactNode; onTopology: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <div className="pilot-map-frame pilot-map-failure" role="alert">地图暂时无法加载 <button onClick={this.props.onTopology}>切换到拓扑视图</button></div> : this.props.children; }
}
export function PilotMapPanel({ events, selectedId, onSelect, topology, refreshKey = 0 }: { events: MapEvent[]; selectedId: string | null; onSelect: (id: string) => void; topology: React.ReactNode; refreshKey?: number }) {
  const [view, setView] = useState<'map' | 'topology'>(DEFAULT_SPATIAL_VIEW);
  const [snapshot, setSnapshot] = useState<{ key: string; values: Record<string, LocationResult> }>({ key: '', values: {} });
  const key = JSON.stringify([refreshKey, [...new Set(events.map(e => e.eventId))].sort()]);
  useEffect(() => {
    const controller = new AbortController();
    setSnapshot({ key, values: {} });
    void loadEventLocations(JSON.parse(key)[1], controller.signal, (id, result) => setSnapshot(s => s.key === key ? { key, values: { ...s.values, [id]: result } } : s));
    return () => controller.abort();
  }, [key]);
  const locations = snapshot.key === key ? snapshot.values : {};
  const located = useMemo(() => events.flatMap(event => {
    const value = locations[event.eventId];
    return value?.kind === 'located' ? [{ ...event, location: value.location }] : [];
  }), [events, locations]);
  const current = selectedId ? locations[selectedId] : undefined;
  return <section className="pilot-map-panel" aria-label="事件空间上下文">
    <header className="pilot-map-heading"><div><h2>{view === 'map' ? 'Pilot 区域地图' : '演练关系拓扑'}</h2><span>{view === 'map' ? '钱塘 · 白杨－金沙湖－下沙高教园' : '处置闭环验证'}</span></div>
      <div role="tablist" aria-label="空间视图" className="pilot-view-tabs">
        <button role="tab" aria-label="地图视图" aria-selected={view === 'map'} onClick={() => setView('map')}><EnvironmentOutlined /> 地图视图</button>
        <button role="tab" aria-label="拓扑视图" aria-selected={view === 'topology'} onClick={() => setView('topology')}><ApartmentOutlined /> 拓扑视图</button>
      </div>
    </header>
    {view === 'map' ? <MapBoundary onTopology={() => setView('topology')}><Suspense fallback={<div className="pilot-map-frame pilot-map-failure" role="status">地图加载中</div>}><RealMapView events={located} selectedId={selectedId} onSelect={onSelect} onTopology={() => setView('topology')} /></Suspense></MapBoundary> : <div className="pilot-topology-view"><p className="event-muted">演练关系拓扑，非真实道路 GIS；不用于定位系统事件。</p>{topology}</div>}
    {view === 'map' && <><div className="pilot-map-caption">公开地图底图 · 系统事件记录，非实时路况 · 已核验位置 {located.length} / {events.length}</div>
    {selectedId && <p className="pilot-location-note" role="status">{!current ? '正在核对事件地图位置...' : current.kind === 'located' ? `位置：${current.location.label} · 绑定路口位置（公开地图近似）` : current.kind === 'error' ? '事件地图位置查询失败，未显示位置标记' : '该事件暂无可核验地图位置'}</p>}
    <span className="pilot-attribution"><a href="https://openfreemap.org/" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a></span></>}
  </section>;
}
