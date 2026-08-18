/** Phase17 Planning / Plan Trajectory Observability 类型 */

export interface PlanListItem {
  planId: string;
  goal: string;
  goalType: string;
  latestVersion: number;
  latestFingerprint: string;
  createdAt: string | null;
  updatedAt: string | null;
  executionCount: number;
  latestExecutionStatus: string | null;
  latestRootRunId: string | null;
  replanCount: number;
}

export interface PlanListResponse {
  total: number;
  page: number;
  pageSize: number;
  plans: PlanListItem[];
}

export interface PlanRunSummary {
  runId: string;
  status: string;
  version: number;
  rootRunId: string | null;
  replannedFromRunId: string | null;
  replannedFromVersion: number | null;
  replannedToRunId: string | null;
  terminationReason: string | null;
  startedAt: string | null;
  completedAt: string | null;
  budgetUsage: Record<string, number>;
  budgetLimits: Record<string, number>;
  stepStatuses: Record<string, string>;
}

export interface PlanDetailResponse {
  plan: { planId: string; goal: string; goalType: string; definitionStatus: string; version: number; planFingerprint: string; createdAt: string };
  definitionId: string;
  runs: PlanRunSummary[];
}

export interface VersionDiff {
  planId: string;
  fromVersion: number;
  toVersion: number;
  addedSteps: string[];
  removedSteps: string[];
  changedSteps: string[];
  carriedForwardSteps: string[];
}

export interface TrajectoryMetrics {
  revisionCount: number;
  replanCount: number;
  recoveryAttempts: number;
  recoverySuccess: number;
  recoveryRate: number | null;
  averageTimeToRecoverySeconds: number | null;
  budgetExhaustions: number;
  loopStops: number;
  toolDenials: number;
  humanInterventions: number;
  carriedForwardCount: number;
  duplicateSideEffectCount: number;
  trajectoryLength: number;
}

export interface TrajectoryRun {
  runId: string;
  version: number;
  status: string;
  parentRunId: string | null;
  childRunId: string | null;
  terminationReason: string | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface TrajectoryResponse {
  canonicalRootRunId: string;
  planId: string;
  finalOutcome: string | null;
  lineage: TrajectoryRun[];
  metrics: TrajectoryMetrics;
  observationSummary: { total: number; byType: Record<string, number> };
}

export interface ObservationItem {
  observationId: string;
  planId: string;
  planVersion: number;
  runId: string;
  type: string;
  status: string;
  scope: string;
  source: string;
  timestamp: string;
  stepId: string | null;
  failureCode: string | null;
  failureReason: string | null;
  metadata: Record<string, unknown>;
}
