/** Phase 14 Observability API */
import type { WorkflowObservability } from '../types/observability';

const API = '/api';

export async function getWorkflowObservability(runId: string): Promise<WorkflowObservability> {
  const resp = await fetch(`${API}/observability/workflows/${encodeURIComponent(runId)}`);
  if (!resp.ok) throw new Error(`Observability fetch failed: ${resp.status}`);
  return resp.json() as Promise<WorkflowObservability>;
}
