/**
 * Phase 13 Simulation Types — Traffic Map & Simulation V1
 *
 * 所有交通数据标记为 SIMULATED / 模拟数据。
 */

// ── 枚举 ───────────────────────────────────────────────────────────

export type CongestionLevel = 'normal' | 'slow' | 'congested' | 'severe';
export type SimulationStatus = 'created' | 'running' | 'completed' | 'reset';
export type ActionType =
  | 'traffic_diversion'
  | 'signal_adjustment'
  | 'lane_control'
  | 'dispatch_coordination'
  | 'monitor'
  | 'close';

// ── 路网 ───────────────────────────────────────────────────────────

export interface TrafficIntersection {
  intersectionId: string;
  name: string;
  longitude: number;
  latitude: number;
  connectedRoadIds: string[];
  signalState: string;
}

export interface TrafficRoadSegment {
  roadId: string;
  name: string;
  fromIntersectionId: string;
  toIntersectionId: string;
  geometry: [number, number][];
  lanes: number;
  capacity: number;
  freeFlowSpeed: number;
}

export interface TrafficCameraSensor {
  cameraId: string;
  name: string;
  longitude: number;
  latitude: number;
  roadId: string;
  status: string;
  simulated: boolean;
}

// ── 运行时 ─────────────────────────────────────────────────────────

export interface TrafficRoadState {
  roadId: string;
  avgSpeed: number;
  vehicleCount: number;
  flow: number;
  occupancy: number;
  queueLength: number;
  congestionLevel: CongestionLevel;
  effectiveCapacity: number;
}

export interface TrafficSnapshot {
  snapshotId: string;
  runId: string;
  sequence: number;
  timestamp: string;
  roadStates: Record<string, TrafficRoadState>;
  intersectionStates: Record<string, string>;
  activeEventIds: string[];
  description: string;
}

export interface TrafficCameraObservation {
  cameraId: string;
  vehicleCount: number;
  avgSpeed: number;
  queueLength: number;
  detectedEvents: string[];
  timestamp: string;
  simulated: boolean;
}

// ── 事件 ───────────────────────────────────────────────────────────

export interface TrafficEvent {
  eventId: string;
  eventType: string;
  severity: string;
  roadId: string;
  intersectionId: string;
  longitude: number;
  latitude: number;
  description: string;
  startedAt: string;
  status: string;
  simulated: boolean;
}

// ── 空间上下文 ─────────────────────────────────────────────────────

export interface SpatialContext {
  event: Record<string, unknown> | null;
  affectedRoad: Record<string, unknown> | null;
  upstreamRoads: Array<Record<string, unknown>>;
  downstreamRoads: Array<Record<string, unknown>>;
  adjacentRoads: Array<Record<string, unknown>>;
  nearbyIntersections: Array<Record<string, unknown>>;
  nearbyCameras: Array<Record<string, unknown>>;
  currentTrafficState: Record<string, Record<string, unknown>>;
  simulated: boolean;
}

// ── 仿真运行 ───────────────────────────────────────────────────────

export interface SimulationRun {
  runId: string;
  scenarioId: string;
  status: SimulationStatus;
  currentSnapshotId: string;
  snapshotCount: number;
  sessionId: string;
  createdAt: string;
}

export interface SimulationScenario {
  scenarioId: string;
  name: string;
  description: string;
  category: string;
  initialEvents: Array<Record<string, unknown>>;
}

// ── 动作 ───────────────────────────────────────────────────────────

export interface SimulationAction {
  actionId: string;
  actionType: ActionType;
  targetIds: string[];
  parameters: Record<string, unknown>;
  source: string;
  workflowRunId: string;
  idempotencyKey: string;
  beforeSnapshotId: string;
  afterSnapshotId: string;
  status: string;
  simulation: boolean;
}

// ── API 响应 ───────────────────────────────────────────────────────

export interface CreateSimulationResponse {
  run: SimulationRun;
  network: GeoJSON.FeatureCollection;
  snapshot: TrafficSnapshot;
  description: string;
}

export interface InjectEventResponse {
  event: TrafficEvent;
  snapshot: TrafficSnapshot;
  beforeState: Record<string, unknown>;
  afterState: Record<string, unknown>;
  impact: {
    speedDelta: number;
    queueDelta: number;
  };
}

export interface SimulationDetail {
  run: Record<string, unknown>;
  snapshot: TrafficSnapshot | null;
  events: Array<Record<string, unknown>>;
  actions: Array<Record<string, unknown>>;
  snapshots: Array<Record<string, unknown>>;
  snapshotCount: number;
  eventCount: number;
}

export interface ScenarioListResponse {
  total: number;
  scenarios: SimulationScenario[];
}
