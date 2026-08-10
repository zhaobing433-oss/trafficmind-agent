/**
 * Simulation API Client — Phase 13
 *
 * All responses are normalized from backend snake_case to frontend camelCase.
 */

import type {
  SimulationScenario,
  ScenarioListResponse,
  CreateSimulationResponse,
  SimulationDetail,
  TrafficSnapshot,
  TrafficRoadState,
  TrafficCameraObservation,
  SpatialContext,
  InjectEventResponse,
  SimulationRun,
  TrafficEvent,
} from '../types/simulation';

const API = '/api';

// ═══════════════════════════════════════════════════════════════════════════════
// Normalization — Backend snake_case → Frontend camelCase
// ═══════════════════════════════════════════════════════════════════════════════

/** Map a single object's snake_case keys to camelCase using a key map. */
function mapKeys<T>(raw: unknown, keyMap: Record<string, string>): T {
  const r = (raw ?? {}) as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [snake, camel] of Object.entries(keyMap)) {
    out[camel] = r[snake] ?? r[camel];
  }
  // Copy any extra keys not in the map
  for (const key of Object.keys(r)) {
    if (!(key in out) && !Object.values(keyMap).includes(key)) {
      out[key] = r[key];
    }
  }
  return out as unknown as T;
}

const RUN_KEYS: Record<string, string> = {
  run_id: 'runId', scenario_id: 'scenarioId',
  current_snapshot_id: 'currentSnapshotId', snapshot_count: 'snapshotCount',
  session_id: 'sessionId', created_at: 'createdAt',
};

const SCENARIO_KEYS: Record<string, string> = {
  scenario_id: 'scenarioId', initial_events: 'initialEvents',
};

const EVENT_KEYS: Record<string, string> = {
  event_id: 'eventId', event_type: 'eventType', road_id: 'roadId',
  intersection_id: 'intersectionId', started_at: 'startedAt',
};

const ROAD_STATE_KEYS: Record<string, string> = {
  road_id: 'roadId', avg_speed: 'avgSpeed', vehicle_count: 'vehicleCount',
  queue_length: 'queueLength', congestion_level: 'congestionLevel',
  effective_capacity: 'effectiveCapacity',
};

const CAMERA_OBS_KEYS: Record<string, string> = {
  camera_id: 'cameraId', vehicle_count: 'vehicleCount', avg_speed: 'avgSpeed',
  queue_length: 'queueLength', detected_events: 'detectedEvents',
};

const SNAPSHOT_KEYS: Record<string, string> = {
  snapshot_id: 'snapshotId', run_id: 'runId',
  road_states: 'roadStates', intersection_states: 'intersectionStates',
  active_event_ids: 'activeEventIds',
};

const ACTION_KEYS: Record<string, string> = {
  action_id: 'actionId', action_type: 'actionType', target_ids: 'targetIds',
  workflow_run_id: 'workflowRunId', idempotency_key: 'idempotencyKey',
  before_snapshot_id: 'beforeSnapshotId', after_snapshot_id: 'afterSnapshotId',
};

export function normalizeRun(raw: unknown): SimulationRun {
  return mapKeys<SimulationRun>(raw, RUN_KEYS);
}

function normalizeEvent(raw: unknown): TrafficEvent {
  return mapKeys<TrafficEvent>(raw, EVENT_KEYS);
}

function normalizeRoadState(raw: unknown): TrafficRoadState {
  return mapKeys<TrafficRoadState>(raw, ROAD_STATE_KEYS);
}

function normalizeCameraObs(raw: unknown): TrafficCameraObservation {
  return mapKeys<TrafficCameraObservation>(raw, CAMERA_OBS_KEYS);
}

function normalizeSnapshot(raw: unknown): TrafficSnapshot {
  const s = mapKeys<Record<string, unknown>>(raw, SNAPSHOT_KEYS);
  // Recursively normalize road states
  if (s.roadStates && typeof s.roadStates === 'object') {
    const rs: Record<string, TrafficRoadState> = {};
    for (const [k, v] of Object.entries(s.roadStates as Record<string, unknown>)) {
      rs[k] = normalizeRoadState(v);
    }
    s.roadStates = rs as unknown as Record<string, TrafficRoadState>;
  }
  return s as unknown as TrafficSnapshot;
}

// ═══════════════════════════════════════════════════════════════════════════════
// API Functions
// ═══════════════════════════════════════════════════════════════════════════════

// ── Scenarios ──────────────────────────────────────────────────────

export async function listScenarios(): Promise<ScenarioListResponse> {
  const resp = await fetch(`${API}/traffic-map/scenarios`);
  if (!resp.ok) throw new Error(`Failed to list scenarios: ${resp.status}`);
  const data = await resp.json();
  return { total: data.total, scenarios: (data.scenarios ?? []).map((s: unknown) => mapKeys<SimulationScenario>(s, SCENARIO_KEYS)) };
}

// ── Simulations ────────────────────────────────────────────────────

export async function createSimulation(
  scenarioId: string,
  sessionId?: string,
): Promise<CreateSimulationResponse> {
  const resp = await fetch(`${API}/traffic-map/simulations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenarioId, sessionId: sessionId || '' }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error((err as { detail?: string }).detail || `Create failed: ${resp.status}`);
  }
  const data = await resp.json();
  return {
    run: normalizeRun(data.run),
    network: data.network,
    snapshot: normalizeSnapshot(data.snapshot),
    description: data.description,
  };
}

export async function getSimulation(runId: string): Promise<SimulationDetail> {
  const resp = await fetch(`${API}/traffic-map/simulations/${encodeURIComponent(runId)}`);
  if (!resp.ok) throw new Error(`Failed to get simulation: ${resp.status}`);
  const data = await resp.json();
  return {
    ...data,
    run: normalizeRun(data.run),
    snapshot: data.snapshot ? normalizeSnapshot(data.snapshot) : null,
    events: (data.events ?? []).map(normalizeEvent),
  };
}

export async function getNetwork(runId: string): Promise<GeoJSON.FeatureCollection> {
  const resp = await fetch(`${API}/traffic-map/simulations/${encodeURIComponent(runId)}/network`);
  if (!resp.ok) throw new Error(`Failed to get network: ${resp.status}`);
  return resp.json();
}

export async function getSnapshot(runId: string): Promise<TrafficSnapshot> {
  const resp = await fetch(`${API}/traffic-map/simulations/${encodeURIComponent(runId)}/snapshot`);
  if (!resp.ok) throw new Error(`Failed to get snapshot: ${resp.status}`);
  return normalizeSnapshot(await resp.json());
}

export async function getRoadState(runId: string, roadId: string): Promise<TrafficRoadState> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/road/${encodeURIComponent(roadId)}/state`,
  );
  if (!resp.ok) throw new Error(`Failed to get road state: ${resp.status}`);
  return normalizeRoadState(await resp.json());
}

export async function getCameraObservation(
  runId: string,
  cameraId: string,
): Promise<TrafficCameraObservation> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/camera/${encodeURIComponent(cameraId)}`,
  );
  if (!resp.ok) throw new Error(`Failed to get camera: ${resp.status}`);
  return normalizeCameraObs(await resp.json());
}

export async function getSpatialContext(
  runId: string,
  eventId: string,
): Promise<SpatialContext> {
  const params = new URLSearchParams({ eventId });
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/spatial-context?${params}`,
  );
  if (!resp.ok) throw new Error(`Failed to get spatial context: ${resp.status}`);
  return resp.json();
}

// ── Events ─────────────────────────────────────────────────────────

export async function injectEvent(
  runId: string,
  body: {
    eventType: string;
    severity: string;
    roadId: string;
    longitude?: number;
    latitude?: number;
    description?: string;
  },
): Promise<InjectEventResponse> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/events`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error((err as { detail?: string }).detail || `Inject event failed: ${resp.status}`);
  }
  const data = await resp.json();
  return {
    event: normalizeEvent(data.event),
    snapshot: normalizeSnapshot(data.snapshot),
    beforeState: data.beforeState,
    afterState: data.afterState,
    impact: data.impact,
  };
}

export async function resetSimulation(
  runId: string,
): Promise<{ run: SimulationRun; snapshot: TrafficSnapshot }> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/reset`,
    { method: 'POST' },
  );
  if (!resp.ok) throw new Error(`Reset failed: ${resp.status}`);
  const data = await resp.json();
  return { run: normalizeRun(data.run), snapshot: normalizeSnapshot(data.snapshot) };
}
