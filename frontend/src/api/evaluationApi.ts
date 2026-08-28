/** Phase 14 Round 3 Evaluation API */
import type { EvalReportSummary, EvalReportFull, EvalCaseDetail, ReportCompare, EvalSummary } from '../types/evaluation';

const API = '/api/evaluation';

export async function listReports(limit = 20): Promise<EvalReportSummary[]> {
  const resp = await fetch(`${API}/reports?limit=${limit}`);
  if (!resp.ok) throw new Error(`List reports failed: ${resp.status}`);
  const data = await resp.json();
  return data.reports ?? [];
}

export async function getReport(reportId: string): Promise<EvalReportFull> {
  const resp = await fetch(`${API}/reports/${encodeURIComponent(reportId)}`);
  if (!resp.ok) throw new Error(`Get report failed: ${resp.status}`);
  return resp.json();
}

export async function getCase(reportId: string, caseId: string): Promise<EvalCaseDetail> {
  const resp = await fetch(`${API}/reports/${encodeURIComponent(reportId)}/cases/${encodeURIComponent(caseId)}`);
  if (!resp.ok) throw new Error(`Get case failed: ${resp.status}`);
  return resp.json();
}

/** Phase20 R2：产品级总览 — 复用 GET /evaluation/reports/{id}/summary（后端为 authority） */
export async function getReportSummary(reportId: string): Promise<EvalSummary> {
  const resp = await fetch(`${API}/reports/${encodeURIComponent(reportId)}/summary`);
  if (!resp.ok) throw new Error(`Get report summary failed: ${resp.status}`);
  return resp.json();
}

export async function compareReports(base: string, target: string): Promise<ReportCompare> {
  const params = new URLSearchParams({ base, target });
  const resp = await fetch(`${API}/compare?${params}`);
  if (!resp.ok) throw new Error(`Compare failed: ${resp.status}`);
  return resp.json();
}
