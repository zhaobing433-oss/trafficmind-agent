/** Phase 9.5 协作运行模型 */

export type RunStatus = 'created' | 'routing' | 'running' | 'arbitrating' | 'fusing'
  | 'completed' | 'partial_success' | 'failed' | 'requires_human_review' | 'interrupted';

export type TaskStatus = 'pending' | 'ready' | 'running' | 'succeeded' | 'retrying'
  | 'failed' | 'timed_out' | 'blocked' | 'skipped';

export interface CollaborationRun {
  runId: string; traceId: string; sessionId: string;
  status: RunStatus; executionEngine: 'orchestrator' | 'legacy';
  protocolVersion: string;
  selectedAgents: string[]; skippedAgents: string[];
  routingReasons: string[];
  tasks: CollaborationTask[];
  agentResults: Record<string, CollaborationAgentResult>;
  conflicts: CollaborationConflict[];
  arbitrationResults: Record<string, unknown>[];
  failedAgents: string[]; limitations: string[];
  budgetUsage: CollaborationBudgetUsage;
  finalDecision: string; fusionSummary: string;
  requiresHumanReview: boolean; degraded: boolean;
  fallbackReason: string;
  startedAt: string; completedAt: string;
  isHydrated?: boolean;
  userQuery?: string;
  contextPolicy?: string;
  fieldSources?: Record<string, string>;
  previousRunContext?: {
    runId: string; summary: string; status: string;
    event: {
      avgSpeed?: number | null; queueLength?: number | null;
      roadName?: string; eventTypeCn?: string;
      nearbySchool?: boolean; nearbyHospital?: boolean; isMainRoad?: boolean;
    };
    updatedAt: string;
  } | null;
}

export interface CollaborationTask {
  taskId: string; agentName: string; taskType: string;
  status: TaskStatus; dependsOn: string[];
  priority: number; attempt: number; maxRetries: number;
  timeoutSeconds: number; error: string;
}

export interface CollaborationAgentResult {
  agentName: string; role: string; status: string;
  findings: string[]; confidence: number;
  suggestion: string; urgency: string;
  evidenceRefs: string[]; attempt: number; duration: number;
  errorCode?: string; errorMessage?: string;
}

export interface CollaborationConflict {
  id: string; type: string; description: string;
  participants: string[]; proposals: Record<string,unknown>[];
  severity: string; status: string; resolution: string;
  resolvedBy: string; requiresHumanReview: boolean;
}

export interface CollaborationBudgetUsage {
  maxAgents: number; maxAgentCalls: number; maxRetries: number;
  maxTotalSeconds: number;
  usedAgentCalls: Record<string,number>; usedRetries: Record<string,number>;
  startedAt: string;
}

export interface CollaborationEvent {
  eventType: string; runId: string; traceId: string;
  sequenceNumber: number; timestamp: string;
  status?: string; taskId?: string; agentName?: string;
  attempt?: number; text?: string;
  payload?: Record<string,unknown>;
}

export const STATUS_LABELS: Record<string, string> = {
  created: '已创建', routing: '正在路由', running: '正在执行',
  arbitrating: '正在仲裁', fusing: '正在融合',
  completed: '已完成', partial_success: '部分完成',
  failed: '执行失败', requires_human_review: '等待人工审核',
  interrupted: '运行已中断',
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: '等待', ready: '就绪', running: '执行中', succeeded: '完成',
  retrying: '重试', failed: '失败', timed_out: '超时',
  blocked: '阻塞', skipped: '跳过',
};

export const AGENT_ROLES: Record<string, string> = {
  CongestionAgent: '拥堵与扩散分析',
  SignalAgent: '信号控制分析',
  PublicSafetyAgent: '医院/学校/事故/行人安全',
  DispatchAgent: '分流/警力/联动处置',
  ConflictArbiter: '冲突仲裁',
  FusionAgent: '最终融合',
};
