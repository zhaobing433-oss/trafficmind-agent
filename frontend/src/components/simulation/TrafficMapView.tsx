/**
 * TrafficMapView — MapLibre GL JS 地图组件
 *
 * Phase 13: 纯本地 inline style，零外部 tile 依赖。
 * 12 roads + 6 intersections + 6 cameras 必须始终可见。
 */
import React, { useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// MapLibre GL JS v6 + Vite: worker MUST be explicitly configured
import maplibreglWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
maplibregl.setWorkerUrl(maplibreglWorkerUrl);

import type { TrafficRoadState, CongestionLevel, TrafficSnapshot } from '../../types/simulation';

const CONGESTION_COLORS: Record<CongestionLevel, string> = {
  normal: '#22C55E', slow: '#F59E0B', congested: '#F97316', severe: '#EF4444',
};
const CONGESTION_WIDTHS: Record<CongestionLevel, number> = {
  normal: 5, slow: 6, congested: 7, severe: 9,
};

interface Props {
  networkGeoJSON: GeoJSON.FeatureCollection | null;
  snapshot: TrafficSnapshot | null;
  onRoadClick?: (roadId: string, state: TrafficRoadState) => void;
  onCameraClick?: (cameraId: string) => void;
  mapHeight?: number | string;
}

// ── Pure local style — no OSM, no external tiles ──────────────────
const LOCAL_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{
    id: 'sim-bg',
    type: 'background',
    paint: { 'background-color': '#E8ECF0' },
  }],
};

// ── ensureSourcesAndLayers — single source of truth ────────────────
function ensureSourcesAndLayers(
  map: maplibregl.Map,
  networkGeoJSON: GeoJSON.FeatureCollection,
  snapshot: TrafficSnapshot | null,
  _fitBounds: boolean,
) {
  const roadStates = snapshot?.roadStates ?? {};

  const roadFeatures: GeoJSON.Feature[] = [];
  const interFeatures: GeoJSON.Feature[] = [];
  const camFeatures: GeoJSON.Feature[] = [];

  for (const feat of networkGeoJSON.features) {
    const props = (feat.properties ?? {}) as Record<string, unknown>;
    const ft = props.featureType as string;
    if (ft === 'road') {
      const st = roadStates[props.roadId as string];
      roadFeatures.push({
        ...feat,
        properties: { ...feat.properties, avgSpeed: st?.avgSpeed ?? 0, queueLength: st?.queueLength ?? 0, congestionLevel: st?.congestionLevel ?? 'normal' },
      });
    } else if (ft === 'intersection') {
      interFeatures.push(feat);
    } else if (ft === 'camera') {
      camFeatures.push(feat);
    }
  }
  const sources: Array<[string, GeoJSON.FeatureCollection]> = [
    ['roads', { type: 'FeatureCollection', features: roadFeatures }],
    ['intersections', { type: 'FeatureCollection', features: interFeatures }],
    ['cameras', { type: 'FeatureCollection', features: camFeatures }],
  ];
  for (const [id, data] of sources) {
    const existing = map.getSource(id);
    if (existing) {
      (existing as maplibregl.GeoJSONSource).setData(data);
    } else {
      map.addSource(id, { type: 'geojson', data });
    }
  }

  // Road layer
  if (!map.getLayer('road-fill')) {
    map.addLayer({
      id: 'road-fill', type: 'line', source: 'roads',
      paint: {
        'line-color': ['match', ['get', 'congestionLevel'], 'severe', CONGESTION_COLORS.severe, 'congested', CONGESTION_COLORS.congested, 'slow', CONGESTION_COLORS.slow, CONGESTION_COLORS.normal],
        'line-width': ['match', ['get', 'congestionLevel'], 'severe', CONGESTION_WIDTHS.severe, 'congested', CONGESTION_WIDTHS.congested, 'slow', CONGESTION_WIDTHS.slow, CONGESTION_WIDTHS.normal],
        'line-opacity': 0.9,
      },
    });
  }
  if (!map.getLayer('inter-fill')) {
    map.addLayer({ id: 'inter-fill', type: 'circle', source: 'intersections', paint: { 'circle-radius': 7, 'circle-color': '#3B82F6', 'circle-stroke-width': 2, 'circle-stroke-color': '#FFF' } });
  }
  if (!map.getLayer('cam-fill')) {
    map.addLayer({ id: 'cam-fill', type: 'circle', source: 'cameras', paint: { 'circle-radius': 7, 'circle-color': '#8B5CF6', 'circle-stroke-width': 2, 'circle-stroke-color': '#FFF' } });
  }

  // Fit bounds on first load
  if (_fitBounds) {
    try {
      const bounds = new maplibregl.LngLatBounds();
      let has = false;
      for (const f of roadFeatures) {
        if (f.geometry.type === 'LineString') {
          for (const c of f.geometry.coordinates as [number, number][]) { bounds.extend(c); has = true; }
        }
      }
      if (has) map.fitBounds(bounds, { padding: 50, duration: 0 });
    } catch (_) { /* ignore */ }
  }
}

// ── Component ──────────────────────────────────────────────────────
export const TrafficMapView: React.FC<Props> = ({ networkGeoJSON, snapshot, onRoadClick, onCameraClick, mapHeight = 500 }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const didFitRef = useRef(false);
  // Refs to avoid stale closure in style.load handler
  const netRef = useRef(networkGeoJSON); netRef.current = networkGeoJSON;
  const snapRef = useRef(snapshot); snapRef.current = snapshot;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    try {
      const map = new maplibregl.Map({ container: containerRef.current, style: LOCAL_STYLE, center: [116.397, 39.906], zoom: 14 });
      map.addControl(new maplibregl.NavigationControl(), 'top-right');
      mapRef.current = map;

      map.on('error', (e: unknown) => { console.error('MapLibre error:', e); });

      // A. Style ready → use refs to get latest data
      map.on('style.load', () => {
        const net = netRef.current;
        const snap = snapRef.current;
        if (net) {
          try {
            ensureSourcesAndLayers(map, net, snap, !didFitRef.current);
            didFitRef.current = true;
          } catch (err) { console.error('ensureSourcesAndLayers failed:', err); }
        }
        // Cursor + click handlers
        map.on('click', (e: maplibregl.MapMouseEvent) => {
          const feats = map.queryRenderedFeatures(e.point, { layers: ['road-fill', 'cam-fill'] });
          if (feats.length === 0) return;
          const props = (feats[0].properties ?? {}) as Record<string, unknown>;
          if (feats[0].layer?.id === 'road-fill') {
            const rid = props.roadId as string;
            const st = (snapshot?.roadStates ?? {})[rid];
            if (rid && st) onRoadClick?.(rid, st);
          } else if (feats[0].layer?.id === 'cam-fill') {
            onCameraClick?.(props.cameraId as string);
          }
        });
        map.on('mouseenter', 'road-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', 'road-fill', () => { map.getCanvas().style.cursor = ''; });
        map.on('mouseenter', 'cam-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', 'cam-fill', () => { map.getCanvas().style.cursor = ''; });
      });
    } catch (err) {
      setMapError(`Map init: ${err instanceof Error ? err.message : String(err)}`);
    }
    return () => { mapRef.current?.remove(); mapRef.current = null; didFitRef.current = false; };
  }, []); // mount only

  // B. Data arrives after style loaded → update sources
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !networkGeoJSON || !map.isStyleLoaded()) return;
    try {
      ensureSourcesAndLayers(map, networkGeoJSON, snapshot, !didFitRef.current);
      didFitRef.current = true;
    } catch (err) { console.error('ensureSourcesAndLayers failed:', err); }
  }, [networkGeoJSON, snapshot]);

  // Render
  return (
    <div style={{ position: 'relative', width: '100%', height: mapHeight, minHeight: 360, borderRadius: 8, overflow: 'hidden', border: '1px solid #E5E7EB', background: '#E8ECF0' }}>
      {mapError ? (
        <div style={{ width: '100%', height: '100%', background: '#1F2937', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9CA3AF', fontSize: 13, flexDirection: 'column', gap: 8, borderRadius: 8 }}>
          <span>地图加载失败</span>
          <span style={{ fontSize: 11 }}>{mapError}</span>
        </div>
      ) : (
        <>
          <div ref={containerRef} style={{ width: '100%', height: '100%', borderRadius: 8 }} />
          <div style={{ position: 'absolute', top: 8, right: 8, background: 'rgba(239,68,68,0.15)', color: '#EF4444', padding: '4px 10px', borderRadius: 4, fontSize: 10, fontWeight: 700, zIndex: 10, pointerEvents: 'none' }}>
            SIMULATED DATA
          </div>
          <div style={{ position: 'absolute', bottom: 8, right: 8, background: 'rgba(255,255,255,0.92)', padding: '6px 10px', borderRadius: 8, fontSize: 10, zIndex: 10 }}>
            {(['severe','congested','slow','normal'] as CongestionLevel[]).map(l => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 18, height: 4, borderRadius: 2, background: CONGESTION_COLORS[l] }} />
                <span style={{ color: '#6B7280' }}>{l === 'severe' ? '严重' : l === 'congested' ? '拥堵' : l === 'slow' ? '缓行' : '正常'}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
