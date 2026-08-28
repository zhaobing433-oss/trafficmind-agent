/** Phase 14 Round 3 Evaluation Dashboard Types */

export interface EvalReportSummary {
  reportId: string; generatedAt: string; datasetVersion: string;
  overallScore: number; passedCases: number; failedCases: number;
  totalCases: number; regressionGatePassed: boolean;
}

export interface RegressionGate {
  passed: boolean; failures: Array<{gate: string; threshold: number; actual: number}>;
  thresholds: Record<string, number>;
}

export interface EvalMetrics {
  totalCases: number; passedCases: number; failedCases: number;
  overallScore: number; eventFieldAccuracy: number; requiredAgentRecall: number;
  agentExactMatch: number; forbiddenAgentRate: number;
  conflictF1: number; safetyPolicyPassRate: number;
  workflowInvariantPassRate: number; outputStructurePassRate: number;
}

export interface EvalCaseDetail {
  caseId: string; name: string; passed: boolean;
  scores: Record<string, number>; failedAssertions: string[];
  diagnostics: Record<string, unknown>;
}

export interface EvalReportFull {
  metadata: Record<string, unknown>; metrics: EvalMetrics;
  regressionGate: RegressionGate; caseResults: EvalCaseDetail[];
}

export interface MetricDelta {
  metric: string; base: number; target: number;
  delta: number; percentagePoints: number; status: 'improved' | 'regressed' | 'unchanged';
}

export interface ReportCompare {
  baseReportId: string; targetReportId: string;
  baseGeneratedAt: string; targetGeneratedAt: string;
  datasetVersionMatch: boolean; frameworkVersionMatch: boolean;
  baseGatePassed: boolean; targetGatePassed: boolean;
  metricsDelta: MetricDelta[];
}

/** Phase20 R2：GET /evaluation/reports/{id}/summary 返回体（SUMMARY_KEYS） */
export interface EvalSummary {
  evaluationId: string;
  generatedAt: string | null;
  commitSha: string | null;
  provider: string | null;
  model: string | null;
  datasetVersion: string | null;
  overallStatus: string | null;
  metricsStatus: string | null;
  gateStatus: string | null;
  totalCases: number | null;
  passedCases: number | null;
  failedCases: number | null;
  overallScore: number | null;
  gates: Array<{ gateId: string; status: string | null; threshold: number | null; actual: number | null }> | null;
}
