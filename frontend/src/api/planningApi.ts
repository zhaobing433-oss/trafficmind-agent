/** Phase17 Planning API 客户端 */

import type {
  PlanListResponse, PlanDetailResponse, VersionDiff, TrajectoryResponse, ObservationItem,
} from '../types/planning';

const API = '/api';

export async function listPlans(params: { page?: number; pageSize?: number; goalType?: string; status?: string; search?: string } = {}): Promise<PlanListResponse> {
  const q = new URLSearchParams();
  if (params.page) q.set('page', String(params.page));
  if (params.pageSize) q.set('pageSize', String(params.pageSize));
  if (params.goalType) q.set('goalType', params.goalType);
  if (params.status) q.set('status', params.status);
  if (params.search) q.set('search', params.search);
  const resp = await fetch(`${API}/planning/plans?${q.toString()}`);
  if (!resp.ok) throw new Error(`list plans failed: ${resp.status}`);
  return resp.json();
}

export async function getPlan(planId: string): Promise<PlanDetailResponse> {
  const resp = await fetch(`${API}/planning/plans/${encodeURIComponent(planId)}`);
  if (!resp.ok) throw new Error(`get plan failed: ${resp.status}`);
  return resp.json();
}

export async function getPlanDiff(planId: string, fromVersion: number, toVersion: number): Promise<VersionDiff> {
  const resp = await fetch(`${API}/planning/plans/${encodeURIComponent(planId)}/diff?fromVersion=${fromVersion}&toVersion=${toVersion}`);
  if (!resp.ok) throw new Error(`diff failed: ${resp.status}`);
  return resp.json();
}

export async function getTrajectory(runId: string): Promise<TrajectoryResponse> {
  const resp = await fetch(`${API}/planning/runs/${encodeURIComponent(runId)}/trajectory`);
  if (!resp.ok) throw new Error(`trajectory failed: ${resp.status}`);
  return resp.json();
}

export async function listObservations(runId: string): Promise<{ runId: string; observations: ObservationItem[] }> {
  const resp = await fetch(`${API}/planning/runs/${encodeURIComponent(runId)}/observations`);
  if (!resp.ok) throw new Error(`observations failed: ${resp.status}`);
  return resp.json();
}
