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

/** Plan 详情（来自 GET /planning/plans/{id} 的 plan.to_dict()） */
export interface PlanDetail {
  planId: string;
  goal: string;
  goalType: string;
  definitionStatus: string;
  version: number;
  planFingerprint: string;
  planningMode: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  eventId: string | null;
  confidence: number | null;
  plannerAudit: {
    planningModeRequested?: string;
    planningModeUsed?: string;
    plannerModel?: string | null;
    proposalId?: string | null;
    confidence?: number | null;
    assumptions?: string[];
    plannerReasonSummary?: string;
    attemptCount?: number;
    fallbackReason?: string | null;
    goalCoverage?: string;
  };
  semanticReplanEnabled: boolean;
  groundedDecisionContextEnabled: boolean;
}

export interface PlanDetailResponse {
  plan: PlanDetail;
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
