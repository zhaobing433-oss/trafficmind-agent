import { pilotGeography } from '../../data/pilot/pilotGeography';
import { record, text } from '../../utils/judgment';

export interface MapEvent {
  eventId: string; roadName?: string; eventType?: string; eventTypeCn?: string;
  riskLevel?: string; status?: string; createdAt?: string; updatedAt?: string;
}
export interface EventMapLocation { eventId: string; coordinates: [number, number]; label: string; bindingId: string }
export type LocationResult = { kind: 'located'; location: EventMapLocation } | { kind: 'unlocated' | 'error' | 'loading' };
export const DEFAULT_SPATIAL_VIEW = 'map' as const;

export const validCoordinates = (c: number[]) => c.length === 2 && c.every(Number.isFinite) && Math.abs(c[0]) <= 180 && Math.abs(c[1]) <= 90;
export function pilotBounds(): [[number, number], [number, number]] {
  const points = pilotGeography.features.map(f => f.geometry.coordinates);
  return [[Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))], [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))]];
}

// The read endpoint returns the active binding. Never join on road names, old history, or a map centroid.
export function locateEvent(eventId: string, response: unknown): EventMapLocation | null {
  const binding = record(record(response).binding);
  if (binding.eventId !== eventId) throw new Error('事件定位关联不匹配');
  if (binding.status !== 'resolved' || !text(binding.bindingId) || !text(binding.resolvedAt) || binding.regionId !== pilotGeography.metadata.regionId) return null;
  const feature = pilotGeography.features.find(f => f.id === binding.intersectionId);
  if (!feature || feature.properties.verificationStatus !== 'verified' || feature.properties.coordinateSystem !== 'WGS84' || !validCoordinates(feature.geometry.coordinates)) return null;
  const current = record(record(record(response).locationContext).intersection);
  if (current.intersectionId !== feature.id || current.regionId !== binding.regionId || current.status !== 'active' || current.verificationStatus !== 'verified') return null;
  // A changed canonical coordinate requires a reviewed visualization update, not a silent stale marker.
  if (current.longitude !== feature.geometry.coordinates[0] || current.latitude !== feature.geometry.coordinates[1]) return null;
  return { eventId, coordinates: [...feature.geometry.coordinates] as [number, number], label: feature.properties.name, bindingId: text(binding.bindingId) };
}
export async function loadEventLocations(ids: string[], signal: AbortSignal, receive: (id: string, value: LocationResult) => void, request: typeof fetch = fetch) {
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(4, ids.length) }, async () => {
    while (!signal.aborted && cursor < ids.length) {
      const id = ids[cursor++];
      try {
        const response = await request(`/api/regional/events/${encodeURIComponent(id)}/location-binding`, { signal });
        if (response.status === 404) { if (!signal.aborted) receive(id, { kind: 'unlocated' }); continue; }
        if (!response.ok) throw new Error('地图位置查询失败');
        const location = locateEvent(id, await response.json());
        if (!signal.aborted) receive(id, location ? { kind: 'located', location } : { kind: 'unlocated' });
      } catch { if (!signal.aborted) receive(id, { kind: 'error' }); }
    }
  }));
}
export function shouldFocusEvent(previous: string | null, selected: string | null, location?: EventMapLocation) {
  return Boolean(selected && previous !== selected && location?.eventId === selected);
}
