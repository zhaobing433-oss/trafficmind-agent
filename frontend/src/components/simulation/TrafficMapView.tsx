import React, { useMemo } from 'react';
import type { CongestionLevel, TrafficEvent, TrafficRoadState, TrafficSnapshot } from '../../types/simulation';
import { visualTokens } from '../../styles/visualTokens';

const { color, radius, shadow } = visualTokens;

const CONGESTION_COLORS: Record<CongestionLevel, string> = {
  normal: '#78909C',
  slow: '#D8A13A',
  congested: '#D9732D',
  severe: '#C94A55',
};

const VIEWBOX_WIDTH = 1000;
const VIEWBOX_HEIGHT = 640;
const GRID_COLS = 3;
const GRID_ROWS = 3;
const GRID_LEFT = 160;
const GRID_RIGHT = 840;
const GRID_TOP = 130;
const GRID_BOTTOM = 470;
const ROAD_STROKE_WIDTH = 8;

type Coord = [number, number];

interface Props {
  networkGeoJSON: GeoJSON.FeatureCollection | null;
  snapshot: TrafficSnapshot | null;
  events?: TrafficEvent[];
  onRoadClick?: (roadId: string, state: TrafficRoadState, roadName?: string) => void;
  onCameraClick?: (cameraId: string) => void;
  mapHeight?: number | string;
  selectedRoadId?: string | null;
  isRunning?: boolean;
}

interface IntersectionPoint {
  id: string;
  name: string;
  original: Coord;
  point: Coord;
  signalState: string;
}

interface SchematicRoad {
  roadId: string;
  name: string;
  path: string;
  midpoint: Coord;
  labelPoint: Coord;
  state: TrafficRoadState | null;
  congestionLevel: CongestionLevel;
  isSelected: boolean;
  hasEvent: boolean;
  showLabel: boolean;
}

interface SchematicCamera {
  cameraId: string;
  name: string;
  point: Coord;
}

interface SchematicEvent {
  eventId: string;
  eventType: string;
  roadId: string;
  point: Coord;
}

interface SchematicTopology {
  intersections: IntersectionPoint[];
  roads: SchematicRoad[];
  cameras: SchematicCamera[];
  events: SchematicEvent[];
  selectedRoadName: string;
}

export const TrafficMapView: React.FC<Props> = ({
  networkGeoJSON,
  snapshot,
  events = [],
  onRoadClick,
  onCameraClick,
  mapHeight = 500,
  selectedRoadId = null,
  isRunning = false,
}) => {
  const topology = useMemo(
    () => buildSchematicTopology(networkGeoJSON, snapshot, events, selectedRoadId),
    [networkGeoJSON, snapshot, events, selectedRoadId],
  );
  const hasTopology = topology.roads.length > 0;

  return (
    <div className="traffic-topology-canvas" style={{ position: 'relative', width: '100%', height: mapHeight, minHeight: 360, borderRadius: radius.md, overflow: 'hidden', border: `1px solid ${color.borderSubtle}`, background: color.surfaceMuted, boxShadow: shadow.subtle }}>
      <style>{`
        .traffic-topology-canvas .traffic-road-layer {
          transition: stroke 160ms ease, opacity 160ms ease, stroke-width 160ms ease;
        }
      `}</style>
      <svg
        role="img"
        aria-label="路网运行态势拓扑"
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ display: 'block', width: '100%', height: '100%', background: color.surfaceMuted }}
      >
        <defs>
          <pattern id="traffic-schematic-grid" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="#E8EDF2" strokeWidth="1" opacity="0.45" />
          </pattern>
          <filter id="traffic-soft-shadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="4" stdDeviation="8" floodColor="#0F172A" floodOpacity="0.08" />
          </filter>
        </defs>

        <rect x="0" y="0" width={VIEWBOX_WIDTH} height={VIEWBOX_HEIGHT} fill={color.surfaceMuted} />
        <rect x="24" y="24" width={VIEWBOX_WIDTH - 48} height={VIEWBOX_HEIGHT - 48} rx="12" fill="url(#traffic-schematic-grid)" stroke="#EEF1F5" />
        <text x="42" y="56" fill={color.text} fontSize="18" fontWeight="650">路网态势</text>
        <text x="42" y="80" fill={color.textMuted} fontSize="12">路网 · 演练拓扑</text>
        <text x={VIEWBOX_WIDTH - 42} y="58" textAnchor="end" fill={color.textMuted} fontSize="12" fontWeight="600">演练模式</text>

        {hasTopology && (
          <>
            <g opacity="0.65">
              <line x1={GRID_LEFT} y1={GRID_TOP - 44} x2={GRID_RIGHT} y2={GRID_TOP - 44} stroke="#DDE5EC" strokeWidth="1" strokeDasharray="5 9" />
              <line x1={GRID_LEFT} y1={GRID_BOTTOM + 44} x2={GRID_RIGHT} y2={GRID_BOTTOM + 44} stroke="#DDE5EC" strokeWidth="1" strokeDasharray="5 9" />
            </g>

            <g>
              {topology.roads.map(road => (
                <g
                  key={road.roadId}
                  role="button"
                  tabIndex={0}
                  onClick={() => road.state && onRoadClick?.(road.roadId, road.state, road.name)}
                  onKeyDown={e => {
                    if ((e.key === 'Enter' || e.key === ' ') && road.state) onRoadClick?.(road.roadId, road.state, road.name);
                  }}
                  style={{ cursor: road.state ? 'pointer' : 'default' }}
                >
                  <path
                    className="traffic-road-layer"
                    d={road.path}
                    fill="none"
                    stroke={road.isSelected ? color.primary : road.hasEvent ? '#EA7B34' : '#CFD8E3'}
                    strokeWidth={road.isSelected ? ROAD_STROKE_WIDTH + 8 : road.hasEvent ? ROAD_STROKE_WIDTH + 5 : ROAD_STROKE_WIDTH + 3}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={road.isSelected ? 0.2 : road.hasEvent ? 0.28 : 0.52}
                  />
                  <path
                    className="traffic-road-layer"
                    d={road.path}
                    fill="none"
                    stroke={CONGESTION_COLORS[road.congestionLevel]}
                    strokeWidth={ROAD_STROKE_WIDTH}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={road.congestionLevel === 'normal' && !road.isSelected ? 0.66 : 0.94}
                  />
                  {road.showLabel && (
                    <g transform={`translate(${road.labelPoint[0]}, ${road.labelPoint[1]})`} filter="url(#traffic-soft-shadow)">
                      <rect x="-84" y="-15" width="168" height="30" rx="6" fill="#FFFFFF" stroke={road.isSelected ? color.primaryBorder : '#E2E8F0'} />
                      <text x="0" y="4" textAnchor="middle" fill={road.isSelected ? color.primary : color.text} fontSize="12" fontWeight="600">{road.name}</text>
                    </g>
                  )}
                </g>
              ))}
            </g>

            <g>
              {topology.intersections.map(inter => (
                <g key={inter.id} transform={`translate(${inter.point[0]}, ${inter.point[1]})`}>
                  <circle r="9" fill="#FFFFFF" stroke={inter.signalState === 'adjusted' ? color.primary : '#CBD5E1'} strokeWidth="1.6" />
                  <circle r="3.2" fill={inter.signalState === 'adjusted' ? color.primary : '#9AA7B6'} />
                  {inter.name && (
                    <text y="29" textAnchor="middle" fill={color.textMuted} fontSize="12" fontWeight="500">{shortLabel(inter.name)}</text>
                  )}
                </g>
              ))}
            </g>

            <g>
              {topology.cameras.map(cam => (
                <g
                  key={cam.cameraId}
                  transform={`translate(${cam.point[0]}, ${cam.point[1]})`}
                  role="button"
                  tabIndex={0}
                  onClick={() => onCameraClick?.(cam.cameraId)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') onCameraClick?.(cam.cameraId);
                  }}
                  style={{ cursor: 'pointer' }}
                >
                  <rect x="-6" y="-6" width="12" height="12" rx="3" fill="#FFFFFF" stroke={color.primaryBorder} strokeWidth="1.4" />
                </g>
              ))}
            </g>

            <g>
              {topology.events.map(ev => (
                <g key={ev.eventId} transform={`translate(${ev.point[0]}, ${ev.point[1]})`} filter="url(#traffic-soft-shadow)">
                  <title>{ev.eventId}</title>
                  <circle r={isRunning ? 18 : 16} fill="#FFF7ED" stroke="#FED7AA" strokeWidth="2" opacity={isRunning ? 0.92 : 0.82} />
                  <path d="M 0 -8 L 8 7 L -8 7 Z" fill="#EA580C" />
                  <text x="0" y="4" textAnchor="middle" fill="#FFFFFF" fontSize="10" fontWeight="700">!</text>
                  <rect x="16" y="-13" width="92" height="26" rx="6" fill="#FFFFFF" stroke="#E2E8F0" />
                  <text x="27" y="4" fill="#9A3412" fontSize="11" fontWeight="650">{eventTypeLabel(ev.eventType)}</text>
                </g>
              ))}
            </g>
          </>
        )}

        {!hasTopology && (
          <g transform={`translate(${VIEWBOX_WIDTH / 2}, ${VIEWBOX_HEIGHT / 2})`}>
            <rect x="-190" y="-62" width="380" height="124" rx="10" fill="#FFFFFF" stroke="#E5EAF0" filter="url(#traffic-soft-shadow)" />
            <text x="0" y="-14" textAnchor="middle" fill={color.text} fontSize="17" fontWeight="650">暂无演练拓扑运行</text>
            <text x="0" y="14" textAnchor="middle" fill={color.textMuted} fontSize="13">事件 · 真实记录</text>
            <text x="0" y="38" textAnchor="middle" fill={color.textMuted} fontSize="13">创建模拟运行后展示路网处置推演</text>
          </g>
        )}
      </svg>

      <div style={{ position: 'absolute', bottom: 10, right: 10, background: 'rgba(255, 255, 255, 0.94)', border: `1px solid ${color.borderSubtle}`, padding: '8px 10px', borderRadius: radius.md, fontSize: 10, zIndex: 10, boxShadow: shadow.subtle }}>
        {(['severe','congested','slow','normal'] as CongestionLevel[]).map(l => (
          <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: l === 'normal' ? 0 : 4 }}>
            <div style={{ width: 22, height: 6, borderRadius: 99, background: CONGESTION_COLORS[l], opacity: l === 'normal' ? 0.62 : 1 }} />
            <span style={{ color: color.textMuted }}>{congestionLabel(l)}</span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 6, borderTop: `1px solid ${color.borderSubtle}`, paddingTop: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: 99, background: '#EA580C' }} />
          <span style={{ color: color.textMuted }}>模拟事件</span>
        </div>
      </div>

      {topology.selectedRoadName && (
        <div style={{ position: 'absolute', left: 12, bottom: 12, maxWidth: 'calc(100% - 180px)', background: 'rgba(255, 255, 255, 0.96)', border: `1px solid ${color.primaryBorder}`, color: color.primary, padding: '7px 10px', borderRadius: radius.md, fontSize: 12, fontWeight: 650, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', boxShadow: shadow.subtle }}>
          当前路段：{topology.selectedRoadName}
        </div>
      )}
    </div>
  );
};

function buildSchematicTopology(
  networkGeoJSON: GeoJSON.FeatureCollection | null,
  snapshot: TrafficSnapshot | null,
  events: TrafficEvent[],
  selectedRoadId: string | null,
): SchematicTopology {
  if (!networkGeoJSON) {
    return { intersections: [], roads: [], cameras: [], events: [], selectedRoadName: '' };
  }

  const roadStates = snapshot?.roadStates ?? {};
  const activeEvents = events.filter(ev => ev.status === 'active');
  const eventRoadIds = new Set(activeEvents.map(ev => ev.roadId).filter(Boolean));
  const rawIntersections = networkGeoJSON.features
    .filter(isPointFeature)
    .filter(feat => getString(feat.properties, 'featureType') === 'intersection')
    .map(feat => ({
      id: getString(feat.properties, 'intersectionId'),
      name: getString(feat.properties, 'name'),
      signalState: getString(feat.properties, 'signalState'),
      original: feat.geometry.coordinates as Coord,
    }))
    .filter(inter => inter.id);

  const positions = layoutIntersections(rawIntersections);
  const intersections: IntersectionPoint[] = rawIntersections.map(inter => ({
    ...inter,
    point: positions.get(inter.id) ?? [VIEWBOX_WIDTH / 2, VIEWBOX_HEIGHT / 2],
  }));

  const roadPairCount = new Map<string, number>();
  const roadMidpoints = new Map<string, Coord>();
  const roads = networkGeoJSON.features
    .filter(isLineFeature)
    .filter(feat => getString(feat.properties, 'featureType') === 'road')
    .map(feat => {
      const roadId = getString(feat.properties, 'roadId');
      const name = getString(feat.properties, 'name') || roadId;
      const coords = feat.geometry.coordinates as Coord[];
      const start = nearestIntersection(coords[0], intersections);
      const end = nearestIntersection(coords[coords.length - 1], intersections);
      const startPoint = start?.point ?? projectFallback(coords[0]);
      const endPoint = end?.point ?? projectFallback(coords[coords.length - 1]);
      const pairKey = [start?.id ?? roadId, end?.id ?? roadId].sort().join('|');
      const pairIndex = roadPairCount.get(pairKey) ?? 0;
      roadPairCount.set(pairKey, pairIndex + 1);
      const offsetIndex = pairIndex % 2 === 0 ? -Math.ceil((pairIndex + 1) / 2) : Math.ceil((pairIndex + 1) / 2);
      const [from, to] = offsetEndpoints(startPoint, endPoint, offsetIndex * 8);
      const midpoint: Coord = [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2];
      const labelPoint = offsetPoint(midpoint, from, to, -22);
      const state = roadStates[roadId] ?? null;
      const congestionLevel = state?.congestionLevel ?? 'normal';
      const isSelected = roadId === selectedRoadId;
      const hasEvent = eventRoadIds.has(roadId);
      roadMidpoints.set(roadId, midpoint);
      return {
        roadId,
        name,
        path: `M ${from[0]} ${from[1]} L ${to[0]} ${to[1]}`,
        midpoint,
        labelPoint,
        state,
        congestionLevel,
        isSelected,
        hasEvent,
        showLabel: Boolean(name) && (isSelected || hasEvent || congestionLevel !== 'normal'),
      };
    });

  const cameras = networkGeoJSON.features
    .filter(isPointFeature)
    .filter(feat => getString(feat.properties, 'featureType') === 'camera')
    .map(feat => {
      const roadId = getString(feat.properties, 'roadId');
      const fallback = projectFallback(feat.geometry.coordinates as Coord);
      return {
        cameraId: getString(feat.properties, 'cameraId'),
        name: getString(feat.properties, 'name'),
        point: offsetCameraPoint(roadMidpoints.get(roadId) ?? fallback),
      };
    })
    .filter(cam => cam.cameraId);

  const markerByRoad = new Map<string, number>();
  const schematicEvents = activeEvents.map(ev => {
    const base = roadMidpoints.get(ev.roadId) ?? [VIEWBOX_WIDTH / 2, VIEWBOX_HEIGHT / 2];
    const n = markerByRoad.get(ev.roadId) ?? 0;
    markerByRoad.set(ev.roadId, n + 1);
    return {
      eventId: ev.eventId,
      eventType: ev.eventType,
      roadId: ev.roadId,
      point: [base[0] + n * 34, base[1] - 34] as Coord,
    };
  });

  const selectedRoadName = roads.find(road => road.roadId === selectedRoadId)?.name ?? '';
  return { intersections, roads, cameras, events: schematicEvents, selectedRoadName };
}

function layoutIntersections(items: Array<{ id: string; original: Coord }>): Map<string, Coord> {
  const out = new Map<string, Coord>();
  const allNumericIds = items.every(item => /^I\d+$/.test(item.id));
  if (allNumericIds && items.length >= 4) {
    for (const item of items) {
      const n = Number(item.id.slice(1)) - 1;
      const col = clamp(n % GRID_COLS, 0, GRID_COLS - 1);
      const row = clamp(Math.floor(n / GRID_COLS), 0, GRID_ROWS - 1);
      out.set(item.id, gridPoint(col, row));
    }
    return out;
  }

  const xs = rankValues(items.map(item => item.original[0]));
  const ys = rankValues(items.map(item => item.original[1])).reverse();
  for (const item of items) {
    const col = clamp(xs.indexOf(item.original[0]), 0, GRID_COLS - 1);
    const row = clamp(ys.indexOf(item.original[1]), 0, GRID_ROWS - 1);
    out.set(item.id, gridPoint(col, row));
  }
  return out;
}

function gridPoint(col: number, row: number): Coord {
  const xStep = (GRID_RIGHT - GRID_LEFT) / (GRID_COLS - 1);
  const yStep = (GRID_BOTTOM - GRID_TOP) / (GRID_ROWS - 1);
  return [GRID_LEFT + col * xStep, GRID_TOP + row * yStep];
}

function nearestIntersection(coord: Coord | undefined, intersections: IntersectionPoint[]): IntersectionPoint | null {
  if (!coord || intersections.length === 0) return null;
  let best: IntersectionPoint | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const inter of intersections) {
    const d = distance(coord, inter.original);
    if (d < bestDistance) {
      best = inter;
      bestDistance = d;
    }
  }
  return best;
}

function offsetEndpoints(start: Coord, end: Coord, amount: number): [Coord, Coord] {
  const [nx, ny] = normalVector(start, end);
  return [
    [start[0] + nx * amount, start[1] + ny * amount],
    [end[0] + nx * amount, end[1] + ny * amount],
  ];
}

function offsetPoint(point: Coord, start: Coord, end: Coord, amount: number): Coord {
  const [nx, ny] = normalVector(start, end);
  return [point[0] + nx * amount, point[1] + ny * amount];
}

function normalVector(start: Coord, end: Coord): Coord {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const len = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
  return [-dy / len, dx / len];
}

function offsetCameraPoint(point: Coord): Coord {
  return [point[0] + 18, point[1] + 18];
}

function projectFallback(coord: Coord | undefined): Coord {
  if (!coord) return [VIEWBOX_WIDTH / 2, VIEWBOX_HEIGHT / 2];
  return [
    GRID_LEFT + ((coord[0] * 1000) % 1) * (GRID_RIGHT - GRID_LEFT),
    GRID_TOP + ((coord[1] * 1000) % 1) * (GRID_BOTTOM - GRID_TOP),
  ];
}

function rankValues(values: number[]): number[] {
  return [...new Set(values)].sort((a, b) => a - b);
}

function isPointFeature(feat: GeoJSON.Feature): feat is GeoJSON.Feature<GeoJSON.Point> {
  return feat.geometry?.type === 'Point';
}

function isLineFeature(feat: GeoJSON.Feature): feat is GeoJSON.Feature<GeoJSON.LineString> {
  return feat.geometry?.type === 'LineString';
}

function getString(props: GeoJSON.GeoJsonProperties | undefined | null, key: string): string {
  const value = props?.[key];
  return typeof value === 'string' ? value : '';
}

function distance(a: Coord, b: Coord): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  return dx * dx + dy * dy;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function shortLabel(label: string): string {
  return label.replace(/（模拟路网）/g, '').replace(/\(模拟路网\)/g, '');
}

function eventTypeLabel(t: string): string {
  const labels: Record<string, string> = {
    accident: '交通事故',
    congestion: '拥堵',
    construction: '施工',
    vehicle_stopped: '车辆滞留',
  };
  return labels[t] ?? (t || '事件');
}

function congestionLabel(level: CongestionLevel): string {
  const labels: Record<CongestionLevel, string> = {
    normal: '正常',
    slow: '缓行',
    congested: '拥堵',
    severe: '严重',
  };
  return labels[level];
}
