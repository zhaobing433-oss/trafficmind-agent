export interface RealityTaggedEvent {
  sourceType?: string;
  datasetReality?: string;
}

const HISTORY_SOURCE_TYPES = new Set([
  'real_public_reported_incident',
  'synthetic_validation',
]);

export function isCurrentEventRecord(event: RealityTaggedEvent): boolean {
  return !HISTORY_SOURCE_TYPES.has(event.sourceType || '')
    && event.datasetReality !== 'real_public_reported_incident_history';
}
