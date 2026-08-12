/**
 * Memory V2 前端类型定义 — Phase 10
 *
 * snake_case → camelCase 转换统一在 API 层。
 * 组件内部只使用 camelCase。
 */

// ================================================================
// Enums
// ================================================================

export type MemoryType =
  | "session_goal"
  | "stable_fact"
  | "constraint"
  | "confirmed_decision"
  | "unresolved_issue"
  | "user_correction"
  | "run_summary"
  | "proposal"
  | "temporary_fact";

export type MemoryItemStatus =
  | "candidate"
  | "active"
  | "confirmed"
  | "rejected"
  | "superseded"
  | "expired";

export type MemorySourceType =
  | "user_explicit"
  | "user_correction"
  | "event_parser"
  | "agent_proposal"
  | "agent_fusion"
  | "human_review"
  | "system_rule";

export type RecallIntent =
  | "fresh_event"
  | "continue_event"
  | "correction"
  | "previous_decision_query"
  | "memory_query"
  | "ambiguous";

// ================================================================
// Core Models
// ================================================================

export interface MemoryItem {
  id: string;
  memoryType: MemoryType;
  scopeType: string;
  sessionId: string;
  memoryKey: string;
  value: Record<string, unknown>;
  textContent: string;
  status: MemoryItemStatus;
  confidence: number;
  authorityLevel: number;
  sourceType: MemorySourceType;
  sourceId: string;
  sourceRunId: string;
  sourceMessageId: string;
  validFrom: string | null;
  validUntil: string | null;
  supersedesId: string;
  dedupKey: string;
  eventThreadId: string;
  createdAt: string;
  updatedAt: string;
  lastAccessedAt: string | null;
  accessCount: number;
}

export interface MemoryEventThread {
  id: string;
  sessionId: string;
  status: "active" | "closed";
  title: string;
  startedRunId: string;
  lastRunId: string;
  createdAt: string;
  updatedAt: string;
  closedAt: string;
  itemCount: number;
  runCount: number;
}

export interface MemorySessionView {
  sessionId: string;
  activeEventThreadId: string;
  eventThreads: MemoryEventThread[];
  summary: {
    totalItems: number;
    activeItems: number;
    confirmedItems: number;
    candidateItems: number;
    supersededItems: number;
    expiredItems: number;
    rejectedItems: number;
  };
  currentThread: Record<string, MemoryItem[]>;
  historicalThreads: MemoryEventThread[];
}

// ================================================================
// Trace Models
// ================================================================

export interface MemoryTraceResponse {
  runId: string;
  hasTrace: boolean;
  message?: string;
  traceId?: string;
  sessionId?: string;
  eventThreadId?: string;
  recallIntent?: RecallIntent;
  recallDecision?: MemoryRecallDecision;
  recallPlan?: Record<string, unknown>;
  candidates?: unknown[];
  selected?: MemorySelectedItem[];
  rejected?: MemoryRejectedItem[];
  injectionMap?: Record<string, AgentMemoryInjection>;
  writeCandidates?: unknown[];
  writeResults?: MemoryWriteResult[];
  tokenEstimate?: number;
  recallLatencyMs?: number;
  writeLatencyMs?: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface MemorySelectedItem {
  memoryId: string;
  memoryType: MemoryType;
  memoryKey: string;
  value: Record<string, unknown>;
  sourceType: MemorySourceType;
  sourceRunId: string;
  eventThreadId: string;
  confidence: number;
  authorityLevel: number;
  score: number;
  reason: string;
}

export interface MemoryRejectedItem {
  memoryType: MemoryType;
  memoryKey: string;
  reason: string;
  sourceRunId: string;
  eventThreadId: string;
  value?: Record<string, unknown>;
}

export interface AgentMemoryInjection {
  items: MemorySelectedItem[];
  itemCount: number;
  allowedTypes: string[];
}

export interface MemoryWriteResult {
  memoryType: MemoryType;
  memoryKey: string;
  action: string;
  reason: string;
  itemId?: string;
  supersededId?: string;
  sourceRunId?: string;
}

// ================================================================
// Helper Constants
// ================================================================

export const MEMORY_TYPE_LABELS: Record<string, string> = {
  session_goal: "会话目标",
  stable_fact: "稳定事实",
  constraint: "约束条件",
  confirmed_decision: "已确认决策",
  unresolved_issue: "未解决问题",
  user_correction: "用户纠正",
  run_summary: "运行摘要",
  proposal: "Agent提案",
  temporary_fact: "临时事实",
};

export const MEMORY_STATUS_LABELS: Record<string, string> = {
  candidate: "候选",
  active: "活跃",
  confirmed: "已确认",
  rejected: "已拒绝",
  superseded: "已覆盖",
  expired: "已过期",
};

export const REJECTION_REASON_LABELS: Record<string, string> = {
  dynamic_field_blocked: "动态交通字段禁止跨轮继承",
  expired: "记忆已过期",
  superseded: "该事实已被新事实覆盖",
  wrong_event_thread: "属于其他交通事件线程",
  cross_session: "属于其他会话",
  current_input_override: "当前输入明确值优先",
  proposal_not_confirmed: "Agent建议尚未确认",
  token_budget_exceeded: "超过本轮记忆Token预算",
  legacy_unscoped_memory: "旧版记忆缺少事件线程范围",
  ambiguous_proposal_reference: "无法唯一确定用户要采用的方案",
  rejected: "已明确拒绝",
  invalid_ttl: "有效期已失效",
  intent_not_allowed: "当前意图不允许召回此类型",
  agent_not_allowed: "该Agent不允许接收此记忆",
  lower_authority_conflict: "新值权威低于已有事实，拒绝覆盖",
};

export interface MemoryRecallDecision {
  primaryIntent: RecallIntent;
  continuePreviousEvent: boolean;
  startsNewEvent: boolean;
  hasCorrection: boolean;
  queriesPreviousDecision: boolean;
  explicitMemoryQuery: boolean;
  confidence: number;
  reasons: string[];
  detectedEntities: Record<string, string>;
  correctedKeys: string[];
  currentEventThreadId: string;
  previousEventThreadId: string;
}

// ================================================================
// Safe defaults
// ================================================================

export const EMPTY_MEMORY_TRACE: MemoryTraceResponse = {
  runId: "",
  hasTrace: false,
  message: "尚无记忆追踪数据",
};

export const EMPTY_MEMORY_SESSION: MemorySessionView = {
  sessionId: "",
  activeEventThreadId: "",
  eventThreads: [],
  summary: {
    totalItems: 0,
    activeItems: 0,
    confirmedItems: 0,
    candidateItems: 0,
    supersededItems: 0,
    expiredItems: 0,
    rejectedItems: 0,
  },
  currentThread: {},
  historicalThreads: [],
};
