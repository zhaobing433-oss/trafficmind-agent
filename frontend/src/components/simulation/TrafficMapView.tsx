/**
 * TrafficMapView — MapLibre GL JS 地图组件
 *
 * 显示 Demo 路网 GeoJSON。
 * 支持底图加载失败 fallback（Demo 图层不依赖外部底图）。
 * Road 按 congestion_level 着色。
 */

import React, { useEffect, useRef, useCallback, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { TrafficRoadState, CongestionLevel, TrafficSnapshot } from '../../types/simulation';

// ── 常量 ───────────────────────────────────────────────────────────

const CONGESTION_COLORS: Record<CongestionLevel, string> = {
  normal: '#22C55E',
  slow: '#F59E0B',
  congested: '#F97316',
  severe: '#EF4444',
};

const CONGESTION_WIDTHS: Record<CongestionLevel, number> = {
  normal: 2.5,
  slow: 3.5,
  congested: 4.5,
  severe: 5.5,
};

// 默认中心 (Demo 路网中心 ≈ 116.397, 39.906)
const DEFAULT_CENTER: [number, number] = [116.397, 39.906];
const DEFAULT_ZOOM = 14;

// ── Props ──────────────────────────────────────────────────────────

interface Props {
  networkGeoJSON: GeoJSON.FeatureCollection | null;
  snapshot: TrafficSnapshot | null;
  onRoadClick?: (roadId: string, state: TrafficRoadState) => void;
  onCameraClick?: (cameraId: string) => void;
  onEventClick?: (eventId: string) => void;
  mapHeight?: number | string;
}

// ── Component ──────────────────────────────────────────────────────

export const TrafficMapView: React.FC<Props> = ({
  networkGeoJSON,
  snapshot,
  onRoadClick,
  onCameraClick,
  onEventClick,
  mapHeight = 500,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [basemapFailed, setBasemapFailed] = useState(false);

  // ── Init Map ────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    try {
      const map = new maplibregl.Map({
        container: containerRef.current,
        style: {
          version: 8,
          sources: {
            'basemap': {
              type: 'raster',
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              tileSize: 256,
              attribution: '© OpenStreetMap contributors',
            },
          },
          layers: [
            {
              id: 'basemap-layer',
              type: 'raster',
              source: 'basemap',
              minzoom: 0,
              maxzoom: 19,
            },
          ],
        },
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
      });

      map.addControl(new maplibregl.NavigationControl(), 'top-right');

      map.on('error', (_e: unknown) => {
        console.warn('MapLibre error:', _e);
      });

      map.on('load', () => {
        // Canvas fallback: if tiles fail, draw dark background
        map.once('idle', () => {
          if (!map.loaded()) {
            setBasemapFailed(true);
          }
        });
      });

      mapRef.current = map;
    } catch (err) {
      setMapError(`地图初始化失败: ${err instanceof Error ? err.message : String(err)}`);
    }

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  // ── Update GeoJSON layers when network / snapshot change ────────
  const prevRunIdRef = useRef<string>('');

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.loaded() || !networkGeoJSON) return;

    const runId = snapshot?.runId ?? '';
    const isNewRun = runId !== prevRunIdRef.current;
    prevRunIdRef.current = runId;

    // Build styled features with road states merged in
    const roadStates = snapshot?.roadStates ?? {};

    const roadFeatures: GeoJSON.Feature[] = [];
    const intersectionFeatures: GeoJSON.Feature[] = [];
    const cameraFeatures: GeoJSON.Feature[] = [];

    for (const feat of networkGeoJSON.features) {
      const props = feat.properties as Record<string, unknown> | null;
      const featureType = props?.featureType as string | undefined;

      if (featureType === 'road') {
        const roadId = props?.roadId as string;
        const state = roadStates[roadId];
        roadFeatures.push({
          ...feat,
          properties: {
            ...feat.properties,
            avgSpeed: state?.avgSpeed ?? 0,
            queueLength: state?.queueLength ?? 0,
            congestionLevel: state?.congestionLevel ?? 'normal',
          },
        });
      } else if (featureType === 'intersection') {
        intersectionFeatures.push(feat);
      } else if (featureType === 'camera') {
        cameraFeatures.push(feat);
      }
    }

    // ── Add / update sources ────────────────────────────────────────
    const roadCollection: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: roadFeatures,
    };
    const interCollection: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: intersectionFeatures,
    };
    const camCollection: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: cameraFeatures,
    };

    // Remove existing layers/sources if switching runs
    if (isNewRun) {
      ['road-fill', 'intersection-fill', 'camera-fill',
       'road-label', 'camera-label',
      ].forEach(id => {
        if (map.getLayer(id)) map.removeLayer(id);
      });
      ['roads', 'intersections', 'cameras',
      ].forEach(id => {
        if (map.getSource(id)) map.removeSource(id);
      });
    }

    // Add sources
    const addOrUpdateSource = (id: string, data: GeoJSON.FeatureCollection) => {
      const src = map.getSource(id);
      if (src && 'setData' in src) {
        (src as maplibregl.GeoJSONSource).setData(data);
      } else if (!src) {
        map.addSource(id, { type: 'geojson', data });
      }
    };

    addOrUpdateSource('roads', roadCollection);
    addOrUpdateSource('intersections', interCollection);
    addOrUpdateSource('cameras', camCollection);

    // ── Road layer ──────────────────────────────────────────────────
    if (!map.getLayer('road-fill')) {
      map.addLayer({
        id: 'road-fill',
        type: 'line',
        source: 'roads',
        paint: {
          'line-color': [
            'match',
            ['get', 'congestionLevel'],
            'severe', CONGESTION_COLORS.severe,
            'congested', CONGESTION_COLORS.congested,
            'slow', CONGESTION_COLORS.slow,
            CONGESTION_COLORS.normal,
          ],
          'line-width': [
            'match',
            ['get', 'congestionLevel'],
            'severe', CONGESTION_WIDTHS.severe,
            'congested', CONGESTION_WIDTHS.congested,
            'slow', CONGESTION_WIDTHS.slow,
            CONGESTION_WIDTHS.normal,
          ],
          'line-opacity': 0.85,
        },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      });
    }

    // ── Intersection layer ──────────────────────────────────────────
    if (!map.getLayer('intersection-fill')) {
      map.addLayer({
        id: 'intersection-fill',
        type: 'circle',
        source: 'intersections',
        paint: {
          'circle-radius': 5,
          'circle-color': '#3B82F6',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#FFFFFF',
        },
      });
    }

    // ── Camera layer ───────────────────────────────────────────────
    if (!map.getLayer('camera-fill')) {
      map.addLayer({
        id: 'camera-fill',
        type: 'circle',
        source: 'cameras',
        paint: {
          'circle-radius': 6,
          'circle-color': '#8B5CF6',
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#FFFFFF',
        },
      });
    }

    // ── Click handlers ──────────────────────────────────────────────
    // Use queryRenderedFeatures on click (maplibre-gl v5 type-safe pattern)
    map.on('click', (e: maplibregl.MapMouseEvent) => {
      const clickedFeatures = map.queryRenderedFeatures(e.point, {
        layers: ['road-fill', 'camera-fill'],
      });
      if (clickedFeatures.length === 0) return;

      const feat = clickedFeatures[0];
      const layerId = feat.layer?.id || '';
      const props = (feat.properties || {}) as Record<string, unknown>;

      if (layerId === 'road-fill') {
        const roadId = props.roadId as string;
        const state = roadStates[roadId];
        if (roadId && state) {
          onRoadClick?.(roadId, state);
        }
      } else if (layerId === 'camera-fill') {
        const cameraId = props.cameraId as string;
        if (cameraId) {
          onCameraClick?.(cameraId);
        }
      }
    });

    // Cursor styles
    map.on('mouseenter', 'road-fill', () => { (map.getCanvas() as HTMLElement).style.cursor = 'pointer'; });
    map.on('mouseleave', 'road-fill', () => { (map.getCanvas() as HTMLElement).style.cursor = ''; });
    map.on('mouseenter', 'camera-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'camera-fill', () => { map.getCanvas().style.cursor = ''; });

  }, [networkGeoJSON, snapshot, onRoadClick, onCameraClick]);

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div style={{ position: 'relative', width: '100%', height: mapHeight }}>
      {mapError ? (
        <div style={{
          width: '100%', height: '100%', background: '#1F2937',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#9CA3AF', fontSize: 13, flexDirection: 'column', gap: 8,
          borderRadius: 8, border: '1px solid #374151',
        }}>
          <span>🗺 地图加载失败</span>
          <span style={{ fontSize: 11, color: '#6B7280' }}>{mapError}</span>
          <span style={{ fontSize: 10, color: '#4B5563' }}>Demo GeoJSON 图层不受影响，可独立显示</span>
        </div>
      ) : (
        <>
          <div ref={containerRef} style={{ width: '100%', height: '100%', borderRadius: 8 }} />
          {/* Basemap fallback notice */}
          {basemapFailed && (
            <div style={{
              position: 'absolute', bottom: 8, left: 8,
              background: 'rgba(31, 41, 55, 0.85)', color: '#F59E0B',
              padding: '4px 10px', borderRadius: 6, fontSize: 10,
              zIndex: 10,
            }}>
              ⚠ 底图加载失败 — 使用离线模式
            </div>
          )}
          {/* SIMULATED watermark */}
          <div style={{
            position: 'absolute', top: 8, right: 8,
            background: 'rgba(239, 68, 68, 0.15)', color: '#EF4444',
            padding: '4px 10px', borderRadius: 4, fontSize: 10,
            fontWeight: 700, zIndex: 10, border: '1px solid #EF444440',
            pointerEvents: 'none',
          }}>
            SIMULATED DATA
          </div>
          {/* Legend */}
          <div style={{
            position: 'absolute', bottom: 8, right: 8,
            background: 'rgba(255, 255, 255, 0.92)', padding: '8px 12px',
            borderRadius: 8, fontSize: 10, zIndex: 10,
            border: '1px solid #E5E7EB', display: 'flex', flexDirection: 'column', gap: 3,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 2, color: '#374151' }}>拥堵等级</div>
            {(['severe', 'congested', 'slow', 'normal'] as CongestionLevel[]).map(level => (
              <div key={level} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{
                  width: 18, height: 4, borderRadius: 2,
                  background: CONGESTION_COLORS[level],
                }} />
                <span style={{ color: '#6B7280' }}>
                  {level === 'severe' ? '严重' : level === 'congested' ? '拥堵' : level === 'slow' ? '缓行' : '正常'}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
