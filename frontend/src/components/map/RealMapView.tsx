import { useEffect, useRef, useState } from 'react';
import { Map, Marker, NavigationControl, AttributionControl, setWorkerUrl, type MapOptions } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { pilotGeography } from '../../data/pilot/pilotGeography';
import { mapStyle } from './mapConfig';
import { pilotBounds, shouldFocusEvent, type MapEvent, type EventMapLocation } from './mapLocation';
import { eventTitle, eventTypeLabel } from '../../utils/display';

// MapLibre 6 needs Vite's bundled worker, including its shared module dependency.
setWorkerUrl(workerUrl);

export default function RealMapView({ events, selectedId, onSelect, onTopology }: {
  events: Array<MapEvent & { location: EventMapLocation }>; selectedId: string | null;
  onSelect: (id: string) => void; onTopology: () => void;
}) {
  const container = useRef<HTMLDivElement>(null), mapRef = useRef<Map | null>(null);
  const selectRef = useRef(onSelect); selectRef.current = onSelect;
  const focused = useRef<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  useEffect(() => {
    let alive = true, failed = false, map: Map | undefined;
    const timeout = setTimeout(() => { if (alive) setState(s => s === 'loading' ? 'error' : s); }, 18000);
    try {
      map = new Map({ container: container.current!, style: mapStyle(), bounds: pilotBounds(), fitBoundsOptions: { padding: 35, maxZoom: 14 },
        minZoom: 9, maxZoom: 18, attributionControl: false, cooperativeGestures: true } as MapOptions);
      mapRef.current = map;
      map.addControl(new NavigationControl({ showCompass: false }), 'top-left');
      map.addControl(new AttributionControl({ compact: false }), 'bottom-right');
      map.on('error', () => { failed = true; if (alive) setState('error'); });
      map.on('load', () => {
        if (!alive || !map) return;
        map.addSource('pilot-intersections', { type: 'geojson', data: pilotGeography as GeoJSON.FeatureCollection });
        map.addLayer({ id: 'pilot-intersections', type: 'circle', source: 'pilot-intersections', paint: { 'circle-radius': 3, 'circle-color': '#47786f', 'circle-opacity': 0.55, 'circle-stroke-width': 1, 'circle-stroke-color': '#ffffff' } });
      });
      map.on('idle', () => { if (alive && !failed && map?.isStyleLoaded() && map.areTilesLoaded()) { clearTimeout(timeout); setState('ready'); } });
    } catch { setState('error'); }
    const resize = new ResizeObserver(() => map?.resize());
    if (container.current) resize.observe(container.current);
    return () => { alive = false; clearTimeout(timeout); resize.disconnect(); mapRef.current = null; map?.remove(); };
  }, []);

  useEffect(() => { focused.current = null; }, [selectedId]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const markers = events.map(event => {
      const element = document.createElement('button');
      const selected = event.eventId === selectedId;
      element.type = 'button'; element.className = `pilot-event-marker${selected ? ' is-selected' : ''}`;
      element.textContent = ({ accident: '事', congestion: '堵', illegal_parking: '停', pedestrian_intrusion: '行', signal_fault: '灯', vehicle_stopped: '滞' } as Record<string, string>)[event.eventType || ''] || eventTypeLabel(event.eventTypeCn || '').slice(0, 1) || '事';
      const title = eventTitle(event);
      element.title = `${title}\n${event.location.label}（绑定路口位置）\n${event.riskLevel || '风险未记录'} · ${event.status || '状态未记录'}\n${event.updatedAt || event.createdAt || '时间未记录'}`;
      element.setAttribute('aria-label', `地图事件：${title}`); element.setAttribute('aria-pressed', String(selected));
      element.dataset.mapEventId = event.eventId;
      element.addEventListener('click', () => selectRef.current(event.eventId));
      return new Marker({ element, anchor: 'bottom' }).setLngLat(event.location.coordinates).addTo(map);
    });
    const location = events.find(event => event.eventId === selectedId)?.location;
    if (shouldFocusEvent(focused.current, selectedId, location)) {
      focused.current = selectedId;
      map.easeTo({ center: location!.coordinates, zoom: Math.max(map.getZoom(), 14), duration: 500 });
    }
    if (!selectedId) focused.current = null;
    return () => markers.forEach(marker => marker.remove());
  }, [events, selectedId]);

  return <div className="pilot-map-frame" data-map-state={state}>
    <div className="pilot-map-canvas" ref={container} aria-label="钱塘 Pilot 公开地图" />
    {state === 'loading' && <div className="pilot-map-message" role="status">地图加载中</div>}
    {state === 'error' && <div className="pilot-map-message" role="alert">地图暂时无法加载 <button onClick={onTopology}>切换到拓扑视图</button></div>}
  </div>;
}
