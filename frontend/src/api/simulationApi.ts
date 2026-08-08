/**
 * Simulation API Client — Phase 13
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
} from '../types/simulation';

const API = '/api';

// ── Scenarios ──────────────────────────────────────────────────────

export async function listScenarios(): Promise<ScenarioListResponse> {
  const resp = await fetch(`${API}/traffic-map/scenarios`);
  if (!resp.ok) throw new Error(`Failed to list scenarios: ${resp.status}`);
  return resp.json();
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
  return resp.json();
}

export async function getSimulation(runId: string): Promise<SimulationDetail> {
  const resp = await fetch(`${API}/traffic-map/simulations/${encodeURIComponent(runId)}`);
  if (!resp.ok) throw new Error(`Failed to get simulation: ${resp.status}`);
  return resp.json();
}

export async function getNetwork(runId: string): Promise<GeoJSON.FeatureCollection> {
  const resp = await fetch(`${API}/traffic-map/simulations/${encodeURIComponent(runId)}/network`);
  if (!resp.ok) throw new Error(`Failed to get network: ${resp.status}`);
  return resp.json();
}

export async function getSnapshot(runId: string): Promise<TrafficSnapshot> {
  const resp = await fetch(`${API}/traffic-map/simulations/${encodeURIComponent(runId)}/snapshot`);
  if (!resp.ok) throw new Error(`Failed to get snapshot: ${resp.status}`);
  return resp.json();
}

export async function getRoadState(runId: string, roadId: string): Promise<TrafficRoadState> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/road/${encodeURIComponent(roadId)}/state`,
  );
  if (!resp.ok) throw new Error(`Failed to get road state: ${resp.status}`);
  return resp.json();
}

export async function getCameraObservation(
  runId: string,
  cameraId: string,
): Promise<TrafficCameraObservation> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/camera/${encodeURIComponent(cameraId)}`,
  );
  if (!resp.ok) throw new Error(`Failed to get camera: ${resp.status}`);
  return resp.json();
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
  return resp.json();
}

export async function resetSimulation(
  runId: string,
): Promise<{ run: Record<string, unknown>; snapshot: TrafficSnapshot }> {
  const resp = await fetch(
    `${API}/traffic-map/simulations/${encodeURIComponent(runId)}/reset`,
    { method: 'POST' },
  );
  if (!resp.ok) throw new Error(`Reset failed: ${resp.status}`);
  return resp.json();
}
