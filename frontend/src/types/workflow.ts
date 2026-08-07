/** Phase 12 Workflow V1 类型定义 */

export type WorkflowRunStatus =
  | 'pending' | 'running' | 'paused'
  | 'awaiting_approval' | 'completed' | 'failed' | 'rejected' | 'cancelled';

export type NodeStatus =
  | 'pending' | 'running' | 'succeeded' | 'failed'
  | 'retrying' | 'skipped' | 'timed_out' | 'awaiting_approval';

export type NodeType =
  | 'trigger' | 'validate_event' | 'rule_router' | 'rag_retrieve'
  | 'memory_context' | 'agent_task' | 'parallel' | 'join'
  | 'evidence_evaluate' | 'risk_gate' | 'human_approval'
  | 'action' | 'wait' | 'monitor' | 'close';

export type ApprovalDecision = 'pending' | 'approved' | 'rejected' | 'edited';

export type DefinitionStatus = 'draft' | 'active' | 'deprecated';

export interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
  category: string;
  status: DefinitionStatus;
  nodes: WorkflowNodeConfig[];
  entryNodeId: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface WorkflowNodeConfig {
  nodeId: string;
  nodeType: NodeType;
  label: string;
  description: string;
  config: Record<string, unknown>;
  nextNodes: string[];
  parallelBranches: string[][];
  condition: string | null;
  timeoutSeconds: number;
  maxAttempts: number;
  retryDelaySeconds: number;
}

export interface WorkflowDefinitionVersion {
  id: string;
  definitionId: string;
  version: number;
  definitionJson: Record<string, unknown>;
  changelog: string;
  createdAt: string;
}

export interface WorkflowRun {
  runId: string;
  definitionId: string;
  version: number;
  sessionId: string;
  eventThreadId: string;
  status: WorkflowRunStatus;
  currentNodeId: string;
  state: WorkflowState;
  startedAt: string;
  updatedAt: string;
  completedAt: string;
  triggeredBy: string;
}

export interface WorkflowState {
  workflowRunId: string;
  workflowDefinitionId: string;
  workflowVersion: number;
  sessionId: string;
  eventThreadId: string;
  currentEvent: Record<string, unknown>;
  stableFacts: Record<string, unknown>;
  dynamicObservations: Record<string, unknown>;
  ragContext: Record<string, unknown>;
  memoryContext: Record<string, unknown>;
  evidenceRefs: Array<Record<string, unknown>>;
  agentOutputs: Record<string, { summary: string; evidenceRefs: string[]; recordedAt: string }>;
  riskAssessment: Record<string, unknown>;
  proposedActions: Array<Record<string, unknown>>;
  approvedActions: Array<Record<string, unknown>>;
  actionResults: Record<string, unknown>;
  currentNode: string;
  status: WorkflowRunStatus;
  attemptCounts: Record<string, number>;
  pendingApproval: Record<string, unknown> | null;
  errors: Array<{ nodeId: string; error: string; attempt: number; timestamp: string }>;
  ragTraceIds: string[];
  agentRunIds: string[];
  approvalIds: string[];
  actionRecordIds: string[];
}

export interface WorkflowNodeRun {
  nodeRunId: string;
  runId: string;
  nodeId: string;
  nodeType: NodeType;
  status: NodeStatus;
  attempt: number;
  maxAttempts: number;
  inputSnapshot: Record<string, unknown>;
  outputSnapshot: Record<string, unknown>;
  error: string;
  startedAt: string;
  completedAt: string;
  durationMs: number;
}

export interface WorkflowEvent {
  eventId: string;
  runId: string;
  nodeId: string;
  eventType: string;
  payload: Record<string, unknown>;
  sequence: number;
  createdAt: string;
}

export interface WorkflowApproval {
  approvalId: string;
  runId: string;
  nodeId: string;
  proposedActions: Array<Record<string, unknown>>;
  editedActions: Array<Record<string, unknown>>;
  decision: ApprovalDecision;
  reviewer: string;
  comment: string;
  createdAt: string;
  decidedAt: string;
}

export interface WorkflowActionRecord {
  actionId: string;
  runId: string;
  nodeId: string;
  actionType: string;
  idempotencyKey: string;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  status: 'pending' | 'executing' | 'succeeded' | 'failed';
  error: string;
  createdAt: string;
  completedAt: string;
}

export interface WorkflowTrace {
  runId: string;
  definitionId: string;
  version: number;
  status: WorkflowRunStatus;
  currentNodeId: string;
  timeline: WorkflowEvent[];
  nodeRuns: Array<{
    nodeId: string;
    nodeType: NodeType;
    status: NodeStatus;
    attempt: number;
    error: string;
    startedAt: string;
    completedAt: string;
  }>;
  actionRecords: WorkflowActionRecord[];
  ragTraceIds: string[];
  agentRunIds: string[];
  approvalIds: string[];
  actionRecordIds: string[];
}

/** SSE 事件名称 */
export const WORKFLOW_SSE_EVENTS = [
  'workflow_started', 'node_started', 'node_completed', 'node_failed',
  'workflow_paused', 'approval_required', 'workflow_resumed',
  'action_started', 'action_completed',
  'workflow_completed', 'workflow_cancelled', 'error', 'done',
] as const;

/** 节点类型中文标签 */
export const NODE_TYPE_LABELS: Record<NodeType, string> = {
  trigger: '触发入口', validate_event: '事件校验', rule_router: '规则路由',
  rag_retrieve: 'RAG检索', memory_context: 'Memory上下文',
  agent_task: 'Agent分析', parallel: '并行执行', join: '汇合',
  evidence_evaluate: '证据评估', risk_gate: '风险门控',
  human_approval: '人工审批', action: '外部动作',
  wait: '等待', monitor: '监控', close: '闭环归档',
};

/** 节点状态颜色映射 */
export const NODE_STATUS_COLORS: Record<NodeStatus, string> = {
  pending: '#d9d9d9', running: '#1890ff', succeeded: '#52c41a',
  failed: '#ff4d4f', retrying: '#faad14', skipped: '#d9d9d9',
  timed_out: '#ff7a45', awaiting_approval: '#722ed1',
};

/** Run 状态颜色映射 */
export const RUN_STATUS_COLORS: Record<WorkflowRunStatus, string> = {
  pending: '#d9d9d9', running: '#1890ff', paused: '#faad14',
  awaiting_approval: '#722ed1', completed: '#52c41a',
  failed: '#ff4d4f', rejected: '#fa541c', cancelled: '#8c8c8c',
};
